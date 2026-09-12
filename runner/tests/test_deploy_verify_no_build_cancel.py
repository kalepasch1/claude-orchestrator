"""A CANCELED deploy that never built is not a failed build.

deployfix-beethoven-07152141 and deployfix-beethoven-07160115 are the evidence: both say
"Vercel project: web / Release status: CANCELED", both carry an EMPTY "# Vercel/build log
tail:", and neither ever produced a touched file. 07152141 was retried to its budget cap
("reached budget cap (4)"). There was no broken build to fix — web/vercel.json sets
git.deploymentEnabled to {"*": false, "master": true}, so a release verified against any
other ref comes back CANCELED with no build events at all.

TERMINAL_BAD treated that as a failed deploy, which queued an unactionable build-fix task
AND force-rolled-back the production branch over a deploy that never touched production.
_ignored_build_cancel already exempted the other flavour of provider-declined-to-build;
these tests pin the missing one, and pin the limit: a CANCELED build with a real error is
still bad.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_verify  # noqa: E402


class TestNoBuildCancel(unittest.TestCase):
    def test_deploys_disabled_for_the_ref_is_not_a_build_failure(self):
        for message in (
            "Deployments are disabled for this branch.",
            "Git deployments are disabled for this project.",
            "The deployment was skipped because deploymentEnabled is false for this ref.",
        ):
            self.assertTrue(
                deploy_verify._no_build_cancel({"state": "CANCELED", "errorMessage": message}),
                message)

    def test_reads_readystate_as_well_as_state(self):
        self.assertTrue(deploy_verify._no_build_cancel(
            {"readyState": "CANCELED", "errorCode": "DEPLOYMENTS_ARE_DISABLED"}))

    def test_a_cancel_with_a_real_error_is_still_bad(self):
        """An operator aborting a genuinely broken build must not be written off."""
        self.assertFalse(deploy_verify._no_build_cancel(
            {"state": "CANCELED", "errorMessage": "Command 'npm run build' exited with 1"}))

    def test_a_bare_cancel_is_still_bad(self):
        self.assertFalse(deploy_verify._no_build_cancel({"state": "CANCELED"}))

    def test_a_failed_build_is_not_a_no_build_cancel(self):
        self.assertFalse(deploy_verify._no_build_cancel(
            {"state": "ERROR", "errorMessage": "deployments are disabled"}))

    def test_never_raises_on_junk(self):
        for dep in (None, {}, {"state": None}):
            self.assertFalse(deploy_verify._no_build_cancel(dep))

    def test_the_combined_predicate_covers_both_flavours(self):
        ignored = {"state": "CANCELED",
                   "errorMessage": "canceled as a result of running the command defined in "
                                   "the Ignored Build Step setting."}
        disabled = {"state": "CANCELED", "errorMessage": "Deployments are disabled"}
        self.assertTrue(deploy_verify._cancel_without_build(ignored))
        self.assertTrue(deploy_verify._cancel_without_build(disabled))
        self.assertFalse(deploy_verify._cancel_without_build({"state": "ERROR"}))


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


class TestRunDoesNotPunishANonBuild(unittest.TestCase):
    def _fake(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [{"app": "app", "vercel_project": "app-prod"}]
        fake.rows["projects"] = [{"id": "p1", "name": "app", "repo_path": "/repo"}]
        fake.rows["releases"] = [{
            "id": "r1", "project": "app", "deploy_status": "building", "from_sha": "aaa",
            "to_sha": "bbb",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }]
        return fake

    def test_no_rollback_and_no_deployfix_when_the_ref_is_disabled(self):
        fake = self._fake()
        disabled = {"state": "CANCELED", "url": "x.vercel.app",
                    "errorMessage": "Deployments are disabled for this branch."}
        with patch.object(deploy_verify, "db", fake), \
             patch.object(deploy_verify, "_latest_deploy", return_value=disabled), \
             patch.object(deploy_verify, "_rollback") as rollback:
            deploy_verify.run()
        rollback.assert_not_called()
        self.assertFalse(any(t == "tasks" and str(r.get("slug", "")).startswith("deployfix-")
                             for t, r in fake.inserts))

    def test_the_release_note_says_why_it_was_not_built(self):
        fake = self._fake()
        disabled = {"state": "CANCELED", "url": "x.vercel.app",
                    "errorMessage": "Deployments are disabled for this branch."}
        with patch.object(deploy_verify, "db", fake), \
             patch.object(deploy_verify, "_latest_deploy", return_value=disabled), \
             patch.object(deploy_verify, "_rollback"):
            deploy_verify.run()
        self.assertTrue(any(t == "releases" and "deploys disabled for this ref" in
                            str(p.get("note", "")) for t, _, p in fake.updates))

    def test_a_real_build_failure_still_queues_a_deployfix(self):
        """The guard must not swallow the case it exists to preserve."""
        fake = self._fake()
        broken = {"state": "ERROR", "url": "x.vercel.app",
                  "errorMessage": "Command 'npm run build' exited with 1"}
        with patch.object(deploy_verify, "db", fake), \
             patch.object(deploy_verify, "_latest_deploy", return_value=broken), \
             patch.object(deploy_verify, "_deployment_events", return_value="build failed"), \
             patch.object(deploy_verify, "_rollback", return_value=True):
            deploy_verify.run()
        self.assertTrue(any(t == "tasks" and str(r.get("slug", "")).startswith("deployfix-")
                            for t, r in fake.inserts))
        self.assertTrue(any(t == "approvals" for t, _ in fake.inserts))


if __name__ == "__main__":
    unittest.main()
