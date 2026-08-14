"""Recovery of the 2026-07-29 lease-RPC night (hotfix/stash-rescue-lease-night-5f879035).

CONTAINMENT ANALYSIS (2026-08-06, against current master)
---------------------------------------------------------
Every code hunk on the rescue branch is ALREADY present on master, and in several places
master has since evolved a strictly better version of the same solution. Re-applying the
branch would have been a regression, so per the recovery contract the work is proved by
focused tests instead of being force-merged.

  runner/db.py
    CONTAINED  CORE_RETRY_RPCS, _is_core_rpc(), and the `retryable = GET or core-RPC POST`
               gate in the request path.
    DIVERGED   The rescue branch put this in _req(); master moved the request loop into
               _req_one() behind multi-endpoint failover. Master's version is kept.
    DIVERGED   HTTP_RETRY_STATUSES grew from {429,500,502,503,504,521,522,523} on the branch
               to {408,429,500,502,503,504,520,521,522,523,524,525} on master. Master wins.
    DIVERGED   Master adds `probe_only` (endpoint probes never retry) and MissingRelationError
               for a 404 on /rest/v1/<table>. Neither exists on the branch. Master wins.

  runner/pipeline_contract.py
    CONTAINED  LEGAL_RX, SECURITY_TASK_ALLOWLIST / LEGAL_TASK_ALLOWLIST, RESTRICTED_OPERATIONS,
               _credential_allows(), _operation_authorized(), and the _safe_route() gate.
    No divergence found; master matches the branch hunk for hunk.

The rescue branches are the provenance record and are deliberately NOT deleted.

What was genuinely missing was the proof. These tests cover the two behaviours the recovery
requirements name: db.py retry (transient retried, permanent surfaced) and the
pipeline_contract gates (allowlisted passes, non-allowlisted restricted op blocked).
"""
import os
import socket
import sys
import unittest
import urllib.error
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db
import pipeline_contract


class _Response:
    def __init__(self, body=b"[]"):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def _http_error(code):
    return urllib.error.HTTPError("https://x", code, "boom", {}, None)


CORE_RPC = "/rest/v1/rpc/acquire_branch_execution_lease"
OTHER_RPC = "/rest/v1/rpc/some_vendor_webhook"
TABLE = "/rest/v1/tasks"


class CoreRpcClassificationTest(unittest.TestCase):
    """Only orchestrator-critical RPCs are retry-eligible writes."""

    def test_lease_rpcs_are_core(self):
        for name in ("acquire_branch_execution_lease",
                     "heartbeat_branch_execution_lease",
                     "release_branch_execution_lease"):
            self.assertTrue(db._is_core_rpc(f"/rest/v1/rpc/{name}"), name)

    def test_task_state_rpcs_are_core(self):
        for name in ("claim_task", "complete_task", "update_task_state"):
            self.assertTrue(db._is_core_rpc(f"/rest/v1/rpc/{name}"), name)

    def test_unknown_rpc_is_not_core(self):
        self.assertFalse(db._is_core_rpc(OTHER_RPC))

    def test_plain_table_path_is_not_an_rpc(self):
        self.assertFalse(db._is_core_rpc(TABLE))

    def test_trailing_slash_is_tolerated(self):
        self.assertTrue(db._is_core_rpc(CORE_RPC + "/"))


class DbRetryTest(unittest.TestCase):
    """Transient failures are retried; permanent ones surface immediately."""

    def setUp(self):
        self.base = "https://example.supabase.co"
        p = patch.multiple(db, URL=self.base, KEY="test-key", HTTP_RETRIES=2)
        p.start()
        self.addCleanup(p.stop)
        sleep = patch.object(db.time, "sleep")
        self.sleep = sleep.start()
        self.addCleanup(sleep.stop)
        pin = patch.object(db, "_pin")
        pin.start()
        self.addCleanup(pin.stop)

    def call(self, method, path, side_effect):
        with patch.object(db.urllib.request, "urlopen", side_effect=side_effect) as m:
            try:
                result = db._req_one(self.base, method, path, "", None, {})
                return result, m
            except BaseException as e:
                return e, m

    # ---- transient -> retried -------------------------------------------------
    def test_core_rpc_post_retries_a_transient_network_error(self):
        result, m = self.call("POST", CORE_RPC,
                              [urllib.error.URLError(socket.gaierror(8, "dns")), _Response()])
        self.assertEqual(result, [])
        self.assertEqual(m.call_count, 2)

    def test_core_rpc_post_retries_a_retryable_http_status(self):
        result, m = self.call("POST", CORE_RPC, [_http_error(503), _Response()])
        self.assertEqual(result, [])
        self.assertEqual(m.call_count, 2)

    def test_get_retries_a_transient_error(self):
        result, m = self.call("GET", TABLE, [_http_error(502), _Response()])
        self.assertEqual(result, [])
        self.assertEqual(m.call_count, 2)

    def test_retry_backs_off_between_attempts(self):
        self.call("POST", CORE_RPC, [_http_error(503), _Response()])
        self.sleep.assert_called_once()

    def test_exhausted_retries_surface_the_last_error(self):
        result, m = self.call("GET", TABLE, [_http_error(503), _http_error(503), _http_error(503)])
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertEqual(m.call_count, 3)  # HTTP_RETRIES=2 -> 3 attempts

    # ---- permanent / non-retryable -> surfaced --------------------------------
    def test_permanent_status_is_not_retried(self):
        result, m = self.call("GET", TABLE, [_http_error(400), _Response()])
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertEqual(m.call_count, 1)

    def test_non_core_rpc_post_is_single_attempt(self):
        result, m = self.call("POST", OTHER_RPC, [_http_error(503), _Response()])
        self.assertIsInstance(result, urllib.error.HTTPError)
        self.assertEqual(m.call_count, 1)

    def test_plain_table_post_is_single_attempt(self):
        result, m = self.call("POST", TABLE, [urllib.error.URLError("down"), _Response()])
        self.assertIsInstance(result, urllib.error.URLError)
        self.assertEqual(m.call_count, 1)

    def test_conflict_becomes_a_transient_db_error(self):
        result, m = self.call("POST", TABLE, [_http_error(409)])
        self.assertIsInstance(result, db.TransientDBError)
        self.assertEqual(m.call_count, 1)

    def test_missing_relation_is_surfaced_not_retried(self):
        result, m = self.call("GET", TABLE, [_http_error(404), _Response()])
        self.assertIsInstance(result, db.MissingRelationError)
        self.assertEqual(m.call_count, 1)

    def test_probe_only_never_retries(self):
        with patch.object(db.urllib.request, "urlopen",
                          side_effect=[urllib.error.URLError("down"), _Response()]) as m:
            with self.assertRaises(urllib.error.URLError):
                db._req_one(self.base, "GET", TABLE, "", None, {}, probe_only=True)
        self.assertEqual(m.call_count, 1)


class CredentialAllowlistGateTest(unittest.TestCase):
    """Allowlisted task kinds keep their privileged class; others are downgraded."""

    def test_unset_allowlist_allows_everything(self):
        with patch.multiple(pipeline_contract,
                            LEGAL_TASK_ALLOWLIST=None, SECURITY_TASK_ALLOWLIST=None):
            self.assertTrue(pipeline_contract._credential_allows("legal", "anything", ""))
            self.assertTrue(pipeline_contract._credential_allows("security", "anything", ""))

    def test_allowlisted_kind_passes(self):
        with patch.object(pipeline_contract, "LEGAL_TASK_ALLOWLIST", {"legal-review"}):
            self.assertTrue(pipeline_contract._credential_allows("legal", "legal-review", ""))

    def test_non_allowlisted_kind_is_blocked(self):
        with patch.object(pipeline_contract, "LEGAL_TASK_ALLOWLIST", {"legal-review"}):
            self.assertFalse(pipeline_contract._credential_allows("legal", "build", ""))

    def test_kind_match_is_case_insensitive(self):
        with patch.object(pipeline_contract, "SECURITY_TASK_ALLOWLIST", {"secfix"}):
            self.assertTrue(pipeline_contract._credential_allows("security", "SecFix", ""))

    def test_empty_allowlist_blocks_everything(self):
        with patch.object(pipeline_contract, "SECURITY_TASK_ALLOWLIST", set()):
            self.assertFalse(pipeline_contract._credential_allows("security", "build", ""))

    def test_allowlisted_legal_task_keeps_the_legal_class(self):
        with patch.object(pipeline_contract, "LEGAL_TASK_ALLOWLIST", {"legal-review"}):
            out = pipeline_contract.classify("update the licensing terms", kind="legal-review")
        self.assertEqual(out["task_class"], "legal")
        self.assertEqual(out["risk"], "legal_posture")

    def test_non_allowlisted_legal_task_is_downgraded_and_flagged(self):
        with patch.object(pipeline_contract, "LEGAL_TASK_ALLOWLIST", {"legal-review"}):
            out = pipeline_contract.classify("update the licensing terms", kind="build")
        self.assertEqual(out["task_class"], "build")
        self.assertTrue(out["security_gated"])

    def test_non_allowlisted_security_task_is_downgraded_and_flagged(self):
        with patch.multiple(pipeline_contract,
                            LEGAL_TASK_ALLOWLIST=None, SECURITY_TASK_ALLOWLIST={"secfix"}):
            out = pipeline_contract.classify("fix the oauth token handling", kind="build")
        self.assertEqual(out["task_class"], "build")
        self.assertTrue(out["security_gated"])

    def test_allowlisted_security_task_keeps_the_security_class(self):
        with patch.multiple(pipeline_contract,
                            LEGAL_TASK_ALLOWLIST=None, SECURITY_TASK_ALLOWLIST={"secfix"}):
            out = pipeline_contract.classify("fix the oauth token handling", kind="secfix")
        self.assertEqual(out["task_class"], "security")


class RestrictedOperationGateTest(unittest.TestCase):
    """Restricted operations require an explicit per-class operation allowlist."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in
                       ("ORCH_LEGAL_ALLOWED_OPERATIONS", "ORCH_SECURITY_ALLOWED_OPERATIONS")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_unset_operation_allowlist_authorizes(self):
        self.assertTrue(pipeline_contract._operation_authorized("task_legal_gate", "legal"))

    def test_listed_operation_is_authorized(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "task_legal_gate,permission_audit"
        self.assertTrue(pipeline_contract._operation_authorized("task_legal_gate", "legal"))

    def test_unlisted_operation_is_refused(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "permission_audit"
        self.assertFalse(pipeline_contract._operation_authorized("task_legal_gate", "legal"))

    def test_empty_operation_allowlist_refuses_everything(self):
        os.environ["ORCH_SECURITY_ALLOWED_OPERATIONS"] = " , "
        self.assertFalse(pipeline_contract._operation_authorized("permission_audit", "security"))

    def test_malformed_operation_name_fails_soft_open(self):
        # A corrupt central push must not wedge the pipeline; it logs and allows.
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "task legal gate!"
        self.assertTrue(pipeline_contract._operation_authorized("task_legal_gate", "legal"))

    def test_route_blocks_an_unauthorized_restricted_operation(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "permission_audit"
        out = pipeline_contract._safe_route("beethoven", "task_legal_gate", "legal")
        self.assertEqual(out["reason"], "operation unauthorized for task class")

    def test_route_allows_an_authorized_restricted_operation(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "task_legal_gate"
        with patch.object(pipeline_contract, "app_triage", None), \
             patch.object(pipeline_contract.model_policy, "choose",
                          return_value=("openai", "gpt-5.4-mini", "policy")):
            out = pipeline_contract._safe_route("beethoven", "task_legal_gate", "legal")
        self.assertNotEqual(out["reason"], "operation unauthorized for task class")
        self.assertEqual(out["provider"], "openai")

    def test_route_ignores_the_gate_for_unprivileged_task_classes(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "permission_audit"
        with patch.object(pipeline_contract, "app_triage", None), \
             patch.object(pipeline_contract.model_policy, "choose",
                          return_value=("openai", "gpt-5.4-mini", "policy")):
            out = pipeline_contract._safe_route("beethoven", "task_legal_gate", "build")
        self.assertNotEqual(out["reason"], "operation unauthorized for task class")

    def test_route_never_blocks_an_unrestricted_operation(self):
        os.environ["ORCH_LEGAL_ALLOWED_OPERATIONS"] = "permission_audit"
        self.assertNotIn("draft_prompt", pipeline_contract.RESTRICTED_OPERATIONS)
        with patch.object(pipeline_contract, "app_triage", None), \
             patch.object(pipeline_contract.model_policy, "choose",
                          return_value=("openai", "gpt-5.4-mini", "policy")):
            out = pipeline_contract._safe_route("beethoven", "draft_prompt", "legal")
        self.assertNotEqual(out["reason"], "operation unauthorized for task class")

    def test_restricted_operation_set_is_the_documented_one(self):
        self.assertEqual(pipeline_contract.RESTRICTED_OPERATIONS,
                         {"task_security_gate", "task_legal_gate",
                          "permission_audit", "credential_validation"})


if __name__ == "__main__":
    unittest.main()
