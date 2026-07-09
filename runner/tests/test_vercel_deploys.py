import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_verify
import deploy_watch
import preview_canary
import release_train


class FakeDB:
    def __init__(self):
        self.updates = []
        self.inserts = []
        self.rows = {}

    def select(self, table, params=None):
        params = params or {}
        rows = list(self.rows.get(table, []))
        if table == "deploy_health" and params.get("app", "").startswith("eq."):
            app = params["app"][3:]
            rows = [r for r in rows if r.get("app") == app]
        if table == "tasks" and params.get("state"):
            return []
        return rows

    def update(self, table, match, patch):
        self.updates.append((table, match, patch))
        return [patch]

    def insert(self, table, row, **kwargs):
        self.inserts.append((table, row))
        return [row]

    def rpc(self, fn, args):
        self.inserts.append(("rpc:" + fn, args))
        return None


class TestDeployVerify(unittest.TestCase):
    def test_vercel_project_comes_from_deploy_health(self):
        health = {"santas-secret-workshop": {"vercel_project": "hisanta"}}
        self.assertEqual(
            deploy_verify._vercel_project("santas-secret-workshop", {"vercel_project": None}, health),
            "hisanta",
        )

    def test_latest_deploy_prefers_matching_release_sha(self):
        deployments = [
            {"state": "READY", "url": "old.vercel.app", "meta": {"githubCommitSha": "old"}},
            {"state": "ERROR", "url": "new.vercel.app", "meta": {"githubCommitSha": "abc123456789"}},
        ]
        with patch.object(deploy_verify, "_vget", return_value={"deployments": deployments}):
            dep = deploy_verify._latest_deploy("app", sha="abc1234567890000")
        self.assertEqual(dep["state"], "ERROR")

    def test_bad_deploy_queues_fix_and_rolls_back(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [{"app": "app", "vercel_project": "app-prod"}]
        fake.rows["projects"] = [{"id": "p1", "name": "app", "repo_path": "", "default_base": "main"}]
        fake.rows["releases"] = [{
            "id": "r1", "project": "app", "deploy_status": "building", "from_sha": "aaa",
            "to_sha": "bbb", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }]
        with patch.object(deploy_verify, "db", fake), \
             patch.object(deploy_verify, "_latest_deploy", return_value={"state": "ERROR", "uid": "d1"}), \
             patch.object(deploy_verify, "_deployment_events", return_value="build failed"):
            deploy_verify.run()
        self.assertTrue(any(t == "tasks" and r["slug"].startswith("deployfix-app-")
                            for t, r in fake.inserts))
        self.assertTrue(any(t == "releases" and p.get("deploy_status") == "rolled_back"
                            for t, _, p in fake.updates))

    def test_vercel_auth_error_does_not_rollback_or_queue_deployfix(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [{"app": "app", "vercel_project": "app-prod"}]
        fake.rows["projects"] = [{"id": "p1", "name": "app", "repo_path": "/repo", "default_base": "main"}]
        fake.rows["releases"] = [{
            "id": "r1", "project": "app", "deploy_status": "building", "from_sha": "aaa",
            "to_sha": "bbb", "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }]
        with patch.object(deploy_verify, "db", fake), \
             patch.object(deploy_verify, "_latest_deploy",
                          return_value={"state": "AUTH_ERROR", "_auth_error": "Vercel API auth failed (403)"}), \
             patch.object(deploy_verify, "_rollback") as rollback:
            deploy_verify.run()
        rollback.assert_not_called()
        self.assertFalse(any(t == "tasks" and r["slug"].startswith("deployfix-app-")
                             for t, r in fake.inserts))
        self.assertTrue(any(t == "releases" and p.get("deploy_status") == "verification_blocked"
                            for t, _, p in fake.updates))
        self.assertTrue(any(t == "approvals" and r["title"] == "Vercel auth blocked deploy verification"
                            for t, r in fake.inserts))


class TestDeployWatch(unittest.TestCase):
    def test_watch_backfills_project_mapping(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [{"app": "app", "vercel_project": "app-prod"}]
        with patch.object(deploy_watch, "db", fake), \
             patch.object(deploy_watch, "TOKEN", "tok"), \
             patch.object(deploy_watch, "_latest_prod", return_value={"state": "READY", "sha": "abc"}):
            deploy_watch.run()
        self.assertIn(("projects", {"name": "app"}, {"vercel_project": "app-prod"}), fake.updates)


class TestReleaseTrainVercel(unittest.TestCase):
    def test_release_train_backfills_vercel_mapping_from_deploy_health(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [{"app": "app", "vercel_project": "app-prod"}]
        with patch.object(release_train, "db", fake):
            row = release_train._deploy_health_for("app")
        self.assertEqual(row["vercel_project"], "app-prod")

    def test_qa_self_heal_queues_one_task(self):
        fake = FakeDB()
        with patch.object(release_train, "db", fake), \
             patch.object(release_train, "_git") as git:
            git.return_value.stdout = "abc changed file.ts"
            release_train._self_heal_qa({"id": "p1", "default_base": "main"}, "app", "/repo",
                                        "orchestrator/dev", "test failed")
        self.assertTrue(any(t == "tasks" and r["slug"].startswith("qafix-app-")
                            for t, r in fake.inserts))

    def test_release_due_ignores_failed_release_attempts(self):
        fake = FakeDB()
        fake.rows["releases"] = [{
            "project": "app",
            "deploy_status": "failed",
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }]
        with patch.object(release_train, "db", fake), \
             patch.object(release_train, "RELEASE_INTERVAL_HOURS", 24):
            due, note = release_train._release_due("app")
        self.assertTrue(due)
        self.assertIn("successful", note)

    def test_release_conflict_self_heal_queues_relfix(self):
        fake = FakeDB()
        with patch.object(release_train, "db", fake), \
             patch.object(release_train, "_git") as git:
            git.return_value.stdout = "< old\n> staged"
            release_train._self_heal_release_conflict({"id": "p1"}, "app", "/repo", "main",
                                                      "prod could not fast-forward")
        self.assertTrue(any(t == "tasks" and r["slug"].startswith("relfix-app-")
                            for t, r in fake.inserts))


class TestPreviewCanary(unittest.TestCase):
    def test_query_preview_returns_none_without_token(self):
        """No hardcoded fallback: absent VERCEL_TOKEN must yield None without hitting the network."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VERCEL_TOKEN", None)
            with patch("urllib.request.urlopen", side_effect=AssertionError("must not open URL")) as mock_open:
                result = preview_canary.query_preview("my-project", "orchestrator/dev")
        self.assertIsNone(result)

    def test_run_skips_gracefully_without_token(self):
        """run() is a no-op when VERCEL_TOKEN is absent — does not raise."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VERCEL_TOKEN", None)
            result = preview_canary.run()
        self.assertEqual(result["checked"], 0)

    def test_no_hardcoded_secret_in_module_source(self):
        """Prove that no long opaque token literal is embedded in preview_canary.py."""
        import inspect
        src = inspect.getsource(preview_canary)
        import re
        # Flag any bare string that looks like a token (>= 20 alphanum/dash/underscore chars)
        suspicious = re.findall(r'["\'][A-Za-z0-9_\-]{20,}["\']', src)
        # Allow the VBASE URL constant and nothing else
        suspicious = [s for s in suspicious if "vercel.com" not in s and "api.vercel" not in s]
        self.assertEqual(suspicious, [],
                         f"Possible hardcoded secret in preview_canary.py: {suspicious}")

    def test_query_preview_matches_branch(self):
        """query_preview returns the deployment whose ref matches the requested branch."""
        deployments = [
            {"state": "READY", "url": "preview-main.vercel.app",
             "meta": {"githubCommitRef": "main"}},
            {"state": "BUILDING", "url": "preview-dev.vercel.app",
             "meta": {"githubCommitRef": "orchestrator/dev"}},
        ]
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok"}), \
             patch.object(preview_canary, "_vget", return_value={"deployments": deployments}):
            dep = preview_canary.query_preview("my-project", "orchestrator/dev")
        self.assertIsNotNone(dep)
        self.assertEqual(dep["url"], "preview-dev.vercel.app")

    def test_query_preview_returns_none_for_unknown_branch(self):
        deployments = [
            {"state": "READY", "url": "preview-main.vercel.app",
             "meta": {"githubCommitRef": "main"}},
        ]
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok"}), \
             patch.object(preview_canary, "_vget", return_value={"deployments": deployments}):
            dep = preview_canary.query_preview("my-project", "orchestrator/dev")
        self.assertIsNone(dep)

    def test_run_files_approval_on_failed_preview(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [
            {"app": "app", "vercel_project": "app-proj", "git_branch": "orchestrator/dev"}
        ]
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok"}), \
             patch.object(preview_canary, "db", fake), \
             patch.object(preview_canary, "query_preview",
                          return_value={"state": "ERROR", "url": "bad.vercel.app"}):
            preview_canary.run()
        self.assertTrue(any(t == "approvals" and r["title"] == "Preview build failed: app"
                            for t, r in fake.inserts))

    def test_run_updates_deploy_health_on_ready_preview(self):
        fake = FakeDB()
        fake.rows["deploy_health"] = [
            {"app": "app", "vercel_project": "app-proj", "git_branch": "orchestrator/dev"}
        ]
        with patch.dict(os.environ, {"VERCEL_TOKEN": "tok"}), \
             patch.object(preview_canary, "db", fake), \
             patch.object(preview_canary, "query_preview",
                          return_value={"state": "READY", "url": "ok.vercel.app"}):
            preview_canary.run()
        self.assertTrue(any(t == "deploy_health" and p.get("preview_state") == "ready"
                            for t, _, p in fake.updates))


if __name__ == "__main__":
    unittest.main(verbosity=2)
