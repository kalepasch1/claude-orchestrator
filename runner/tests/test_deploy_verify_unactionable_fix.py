"""A build-fix task with no build log has nothing to act on; do not file it.

deployfix-beethoven-07160115 (and its sibling -07152141) were filed with "Release status:
CANCELED" and an EMPTY "# Vercel/build log tail:". The prompt asks an executor to "fix the
smallest build/deploy issue and make the production build pass" — from no evidence at all.
Neither task ever produced a touched file, and -07152141 was retried until it hit "reached
budget cap (4)", re-deriving the same nothing each time.

Refusing to file such a task is the fix. The limit matters as much as the rule: an ERROR
with no log still gets queued, because ERROR means a build ran and failed.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_verify  # noqa: E402


class TestUnactionableDeployFix(unittest.TestCase):
    def test_canceled_with_no_log_is_unactionable(self):
        reason = deploy_verify._unactionable_deploy_fix("CANCELED", "")
        self.assertTrue(reason)
        self.assertIn("empty build log", reason)

    def test_whitespace_only_log_counts_as_empty(self):
        self.assertTrue(deploy_verify._unactionable_deploy_fix("CANCELED", "   \n\t "))

    def test_state_matching_is_case_insensitive(self):
        self.assertTrue(deploy_verify._unactionable_deploy_fix("canceled", ""))

    def test_canceled_WITH_a_log_is_actionable(self):
        self.assertEqual(deploy_verify._unactionable_deploy_fix("CANCELED", "npm ERR!"), "")

    def test_error_with_no_log_is_still_actionable(self):
        """ERROR means a build ran and failed; a missing log is a fetch problem."""
        self.assertEqual(deploy_verify._unactionable_deploy_fix("ERROR", ""), "")

    def test_journey_failure_is_still_actionable(self):
        self.assertEqual(deploy_verify._unactionable_deploy_fix("journey_failed", ""), "")

    def test_unconfirmed_state_is_still_actionable(self):
        """A stuck, never-confirmed deploy is a real problem worth a task."""
        self.assertEqual(deploy_verify._unactionable_deploy_fix(None, ""), "")


class FakeDB:
    def __init__(self):
        self.rows = {}
        self.inserts = []
        self.updates = []

    def select(self, table, _params=None):
        return list(self.rows.get(table, []))

    def insert(self, table, record):
        self.inserts.append((table, record))
        return {"id": "new"}

    def update(self, table, match, payload):
        self.updates.append((table, match, payload))
        return payload


class TestQueueDeployFixGate(unittest.TestCase):
    def _release(self):
        return {"id": "r1", "project": "app", "to_sha": "bbb",
                "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def test_no_task_is_filed_without_evidence(self):
        fake = FakeDB()
        with patch.object(deploy_verify, "db", fake):
            deploy_verify._queue_deploy_fix({"id": "p1"}, self._release(), "CANCELED",
                                            "app-prod", log_tail="")
        self.assertEqual(fake.inserts, [])

    def test_a_task_is_filed_when_there_is_something_to_act_on(self):
        fake = FakeDB()
        with patch.object(deploy_verify, "db", fake):
            deploy_verify._queue_deploy_fix({"id": "p1"}, self._release(), "ERROR",
                                            "app-prod", log_tail="npm ERR! build failed")
        self.assertTrue(any(t == "tasks" and str(r.get("slug", "")).startswith("deployfix-app-")
                            for t, r in fake.inserts))

    def test_the_filed_prompt_carries_the_log(self):
        fake = FakeDB()
        with patch.object(deploy_verify, "db", fake):
            deploy_verify._queue_deploy_fix({"id": "p1"}, self._release(), "ERROR",
                                            "app-prod", log_tail="npm ERR! build failed")
        prompts = [r.get("prompt", "") for t, r in fake.inserts if t == "tasks"]
        self.assertTrue(any("npm ERR! build failed" in p for p in prompts))

    def test_a_missing_project_id_still_files_nothing_and_does_not_raise(self):
        fake = FakeDB()
        with patch.object(deploy_verify, "db", fake):
            deploy_verify._queue_deploy_fix({}, self._release(), "ERROR", "app-prod", "log")
        self.assertEqual(fake.inserts, [])


if __name__ == "__main__":
    unittest.main()
