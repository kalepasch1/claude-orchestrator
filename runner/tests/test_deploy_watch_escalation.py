import datetime
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deploy_watch


class FakeDB:
    def __init__(self):
        self.inserts = []
        self.selects = []
        self.rows = {}

    def select(self, table, params=None):
        params = params or {}
        self.selects.append((table, params))
        rows = list(self.rows.get(table, []))
        # Filter by last_deploy_state
        if table == "deploy_health" and params.get("last_deploy_state", "").startswith("eq."):
            state = params["last_deploy_state"][3:]
            rows = [r for r in rows if r.get("last_deploy_state") == state]
        # Filter by slug
        if table == "tasks" and params.get("slug", "").startswith("eq."):
            slug = params["slug"][3:]
            rows = [r for r in rows if r.get("slug") == slug]
        # Filter by title for approvals
        if table == "approvals" and params.get("title", "").startswith("eq."):
            title = params["title"][3:]
            rows = [r for r in rows if r.get("title") == title]
        # Filter by name for projects
        if table == "projects" and params.get("name", "").startswith("eq."):
            name = params["name"][3:]
            rows = [r for r in rows if r.get("name") == name]
        return rows

    def insert(self, table, row, **kw):
        self.inserts.append((table, row))
        return [row]

    def update(self, table, match, patch):
        return [patch]

    def rpc(self, fn, args):
        return None


class TestEscalateErrorApps(unittest.TestCase):
    def setUp(self):
        self.fake = FakeDB()
        self.patches = [
            patch.object(deploy_watch, "db", self.fake),
        ]
        for p in self.patches:
            p.start()
        # Override threshold for testing
        self._orig = deploy_watch.RED_ALERT_HOURS
        deploy_watch.RED_ALERT_HOURS = 6

    def tearDown(self):
        deploy_watch.RED_ALERT_HOURS = self._orig
        for p in self.patches:
            p.stop()

    def test_no_error_apps_no_action(self):
        self.fake.rows["deploy_health"] = []
        deploy_watch._escalate_error_apps()
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        self.assertEqual(len(approval_inserts), 0)

    def test_error_below_threshold_no_action(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        recent = (now - datetime.timedelta(hours=2)).isoformat()
        self.fake.rows["deploy_health"] = [
            {"app": "myapp", "last_deploy_state": "ERROR", "updated_at": recent},
        ]
        deploy_watch._escalate_error_apps()
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        self.assertEqual(len(approval_inserts), 0)

    def test_error_above_threshold_creates_card_and_task(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=10)).isoformat()
        self.fake.rows["deploy_health"] = [
            {"app": "myapp", "last_deploy_state": "ERROR", "updated_at": old},
        ]
        self.fake.rows["approvals"] = []
        self.fake.rows["tasks"] = []
        self.fake.rows["projects"] = [{"id": "proj-123", "name": "myapp"}]
        deploy_watch._escalate_error_apps()
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        task_inserts = [i for i in self.fake.inserts if i[0] == "tasks"]
        self.assertEqual(len(approval_inserts), 1)
        self.assertIn("red alert", approval_inserts[0][1]["title"].lower())
        self.assertEqual(approval_inserts[0][1]["kind"], "ops")
        self.assertEqual(len(task_inserts), 1)
        self.assertTrue(task_inserts[0][1]["slug"].startswith("deployfix-myapp-"))
        self.assertEqual(task_inserts[0][1]["kind"], "bugfix")
        self.assertEqual(task_inserts[0][1]["state"], "QUEUED")

    def test_dedupe_approval_card(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=10)).isoformat()
        self.fake.rows["deploy_health"] = [
            {"app": "myapp", "last_deploy_state": "ERROR", "updated_at": old},
        ]
        self.fake.rows["approvals"] = [
            {"id": "existing", "title": "Deploy ERROR red alert: myapp"},
        ]
        self.fake.rows["tasks"] = []
        self.fake.rows["projects"] = [{"id": "proj-123", "name": "myapp"}]
        deploy_watch._escalate_error_apps()
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        self.assertEqual(len(approval_inserts), 0, "Should not duplicate approval card")

    def test_dedupe_task(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=10)).isoformat()
        today = now.strftime("%Y%m%d")
        self.fake.rows["deploy_health"] = [
            {"app": "myapp", "last_deploy_state": "ERROR", "updated_at": old},
        ]
        self.fake.rows["approvals"] = []
        self.fake.rows["tasks"] = [
            {"id": "task-existing", "slug": f"deployfix-myapp-{today}"},
        ]
        self.fake.rows["projects"] = [{"id": "proj-123", "name": "myapp"}]
        deploy_watch._escalate_error_apps()
        task_inserts = [i for i in self.fake.inserts if i[0] == "tasks"]
        self.assertEqual(len(task_inserts), 0, "Should not duplicate task")

    def test_no_project_skips_task(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=10)).isoformat()
        self.fake.rows["deploy_health"] = [
            {"app": "unknown-app", "last_deploy_state": "ERROR", "updated_at": old},
        ]
        self.fake.rows["approvals"] = []
        self.fake.rows["tasks"] = []
        self.fake.rows["projects"] = []
        deploy_watch._escalate_error_apps()
        # Card created, but no task (no matching project)
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        task_inserts = [i for i in self.fake.inserts if i[0] == "tasks"]
        self.assertEqual(len(approval_inserts), 1)
        self.assertEqual(len(task_inserts), 0)

    def test_z_suffix_timestamp(self):
        """Timestamps with Z suffix are handled correctly."""
        now = datetime.datetime.now(datetime.timezone.utc)
        old = (now - datetime.timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.fake.rows["deploy_health"] = [
            {"app": "myapp", "last_deploy_state": "ERROR", "updated_at": old},
        ]
        self.fake.rows["approvals"] = []
        self.fake.rows["tasks"] = []
        self.fake.rows["projects"] = [{"id": "proj-123", "name": "myapp"}]
        deploy_watch._escalate_error_apps()
        approval_inserts = [i for i in self.fake.inserts if i[0] == "approvals"]
        self.assertEqual(len(approval_inserts), 1)


if __name__ == "__main__":
    unittest.main()
