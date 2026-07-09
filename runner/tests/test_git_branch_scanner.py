import os
import sys
import unittest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import git_branch_scanner

PROJ = {"id": "p1", "name": "myapp", "repo_path": "/repo"}
OLD_TS = "2020-01-01T00:00:00Z"   # well over MIN_AGE_SECONDS
NEW_TS = "2099-01-01T00:00:00Z"   # far in the future, always "too new"


def _task(slug="feat-x", state="DONE", ts=OLD_TS, project_id="p1"):
    return {"id": "t1", "slug": slug, "project_id": project_id,
            "state": state, "note": "", "created_at": ts}


def _fake_db(tasks=None, projects=None, inserted=None, select_side=None):
    fake = MagicMock()
    projects = projects or [PROJ]
    tasks = tasks or []

    def _select(table, params=None):
        if table == "projects":
            return projects
        if table == "tasks":
            if select_side:
                return select_side(table, params)
            return tasks
        return []

    fake.select.side_effect = _select
    if inserted is not None:
        fake.insert.side_effect = lambda tbl, row, **kw: inserted.append((tbl, row))
    return fake


# ---------------------------------------------------------------------------
# detect()
# ---------------------------------------------------------------------------

class DetectTest(unittest.TestCase):

    def test_empty_when_no_tasks(self):
        fake = _fake_db(tasks=[])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_returns_issue_when_branch_missing(self):
        fake = _fake_db(tasks=[_task()])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["slug"], "feat-x")
        self.assertEqual(issues[0]["issue_type"], "missing_branch")

    def test_no_issue_when_local_branch_exists(self):
        fake = _fake_db(tasks=[_task()])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists_local", return_value=True), \
             patch.object(git_branch_scanner, "_branch_exists_remote", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_no_issue_when_remote_branch_exists(self):
        fake = _fake_db(tasks=[_task()])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists_local", return_value=False), \
             patch.object(git_branch_scanner, "_branch_exists_remote", return_value=True):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_skips_recovery_slugs(self):
        t = _task(slug="recover-missing-branch-feat-x")
        fake = _fake_db(tasks=[t])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_skips_rework_recovery_slugs(self):
        t = _task(slug="rework-3-recover-missing-branch-feat-x")
        fake = _fake_db(tasks=[t])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_skips_tasks_too_new(self):
        t = _task(ts=NEW_TS)
        fake = _fake_db(tasks=[t])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=300)
        self.assertEqual(issues, [])

    def test_skips_empty_slug(self):
        t = _task(slug="")
        fake = _fake_db(tasks=[t])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues, [])

    def test_branch_name_uses_agent_prefix(self):
        fake = _fake_db(tasks=[_task(slug="my-task")])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues[0]["branch"], "agent/my-task")

    def test_includes_project_name_in_issue(self):
        fake = _fake_db(tasks=[_task()])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues[0]["project_name"], "myapp")

    def test_includes_task_state_in_issue(self):
        fake = _fake_db(tasks=[_task(state="QUEUED")])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(issues[0]["task_state"], "QUEUED")

    def test_handles_task_with_unknown_project(self):
        t = _task(project_id="unknown")
        fake = _fake_db(tasks=[t])
        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", return_value=False):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["project_name"], "")

    def test_multiple_tasks_mixed_results(self):
        tasks = [
            _task(slug="a", state="DONE"),
            _task(slug="b", state="QUEUED"),
        ]
        fake = _fake_db(tasks=tasks)
        branch_state = {"agent/a": False, "agent/b": True}

        def _exists(repo, branch):
            return branch_state.get(branch, False)

        with patch.object(git_branch_scanner, "db", fake), \
             patch.object(git_branch_scanner, "_branch_exists", side_effect=_exists):
            issues = git_branch_scanner.detect(min_age_s=0)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["slug"], "a")


# ---------------------------------------------------------------------------
# store_issues()
# ---------------------------------------------------------------------------

class StoreIssuesTest(unittest.TestCase):

    def test_upserts_controls_row(self):
        inserted = []
        fake = _fake_db(inserted=inserted)
        with patch.object(git_branch_scanner, "db", fake):
            git_branch_scanner.store_issues([])
        self.assertEqual(len(inserted), 1)
        tbl, row = inserted[0]
        self.assertEqual(tbl, "controls")
        self.assertEqual(row["key"], git_branch_scanner.CONTROL_KEY)

    def test_payload_count_matches_issues(self):
        inserted = []
        fake = _fake_db(inserted=inserted)
        issues = [{"slug": "x"}, {"slug": "y"}]
        with patch.object(git_branch_scanner, "db", fake):
            payload = git_branch_scanner.store_issues(issues)
        self.assertEqual(payload["count"], 2)

    def test_payload_value_is_json_string(self):
        inserted = []
        fake = _fake_db(inserted=inserted)
        with patch.object(git_branch_scanner, "db", fake):
            git_branch_scanner.store_issues([{"slug": "a"}])
        _, row = inserted[0]
        parsed = __import__("json").loads(row["value"])
        self.assertEqual(parsed["count"], 1)

    def test_survives_db_error(self):
        fake = MagicMock()
        fake.select.return_value = []
        fake.insert.side_effect = RuntimeError("db down")
        with patch.object(git_branch_scanner, "db", fake):
            payload = git_branch_scanner.store_issues([])   # must not raise
        self.assertEqual(payload["count"], 0)


# ---------------------------------------------------------------------------
# fix()
# ---------------------------------------------------------------------------

class FixTest(unittest.TestCase):

    def _issue(self, slug="feat-x", project_id="p1"):
        return {"slug": slug, "project_id": project_id,
                "branch": f"agent/{slug}", "task_state": "DONE"}

    def _db_no_existing(self, inserted):
        fake = MagicMock()
        fake.select.return_value = []
        fake.insert.side_effect = lambda tbl, row, **kw: inserted.append((tbl, row))
        return fake

    def test_queues_recovery_task(self):
        inserted = []
        fake = self._db_no_existing(inserted)
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([self._issue()])
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["skipped"], 0)
        tasks = [r for t, r in inserted if t == "tasks"]
        self.assertEqual(len(tasks), 1)

    def test_recovery_slug_has_prefix(self):
        inserted = []
        fake = self._db_no_existing(inserted)
        with patch.object(git_branch_scanner, "db", fake):
            git_branch_scanner.fix([self._issue(slug="my-feat")])
        _, row = inserted[0]
        self.assertTrue(row["slug"].startswith(git_branch_scanner.RECOVERY_PREFIX))
        self.assertIn("my-feat", row["slug"])

    def test_recovery_task_uses_ollama(self):
        inserted = []
        fake = self._db_no_existing(inserted)
        with patch.object(git_branch_scanner, "db", fake):
            git_branch_scanner.fix([self._issue()])
        _, row = inserted[0]
        self.assertEqual(row["force_coder"], "ollama")
        self.assertEqual(row["model"], "ollama")

    def test_skips_when_active_recovery_exists(self):
        fake = MagicMock()
        fake.select.return_value = [{"id": "existing"}]
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([self._issue()])
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["skipped"], 1)
        fake.insert.assert_not_called()

    def test_skips_missing_slug(self):
        issue = {"slug": "", "project_id": "p1", "branch": "agent/", "task_state": "DONE"}
        fake = MagicMock()
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([issue])
        self.assertEqual(result["skipped"], 1)
        fake.insert.assert_not_called()

    def test_skips_missing_project_id(self):
        issue = {"slug": "feat-x", "project_id": None, "branch": "agent/feat-x", "task_state": "DONE"}
        fake = MagicMock()
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([issue])
        self.assertEqual(result["skipped"], 1)
        fake.insert.assert_not_called()

    def test_survives_insert_error(self):
        fake = MagicMock()
        fake.select.return_value = []
        fake.insert.side_effect = RuntimeError("insert failed")
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([self._issue()])
        self.assertEqual(result["queued"], 0)
        self.assertEqual(result["skipped"], 1)

    def test_survives_select_error(self):
        fake = MagicMock()
        fake.select.side_effect = RuntimeError("select failed")
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([self._issue()])
        self.assertEqual(result["skipped"], 1)

    def test_empty_issues_returns_zeros(self):
        fake = MagicMock()
        with patch.object(git_branch_scanner, "db", fake):
            result = git_branch_scanner.fix([])
        self.assertEqual(result, {"queued": 0, "skipped": 0})


# ---------------------------------------------------------------------------
# run() integration
# ---------------------------------------------------------------------------

class RunTest(unittest.TestCase):

    def test_run_calls_detect_store_fix(self):
        issues = [{"slug": "x", "project_id": "p1", "branch": "agent/x", "task_state": "DONE"}]
        with patch.object(git_branch_scanner, "detect", return_value=issues) as d, \
             patch.object(git_branch_scanner, "store_issues", return_value={}) as s, \
             patch.object(git_branch_scanner, "fix", return_value={"queued": 1, "skipped": 0}) as f:
            result = git_branch_scanner.run()
        d.assert_called_once()
        s.assert_called_once_with(issues)
        f.assert_called_once_with(issues)
        self.assertEqual(result["detected"], 1)
        self.assertEqual(result["queued"], 1)

    def test_run_returns_summary_keys(self):
        with patch.object(git_branch_scanner, "detect", return_value=[]), \
             patch.object(git_branch_scanner, "store_issues", return_value={}), \
             patch.object(git_branch_scanner, "fix", return_value={"queued": 0, "skipped": 0}):
            result = git_branch_scanner.run()
        self.assertIn("detected", result)
        self.assertIn("queued", result)
        self.assertIn("skipped", result)


if __name__ == "__main__":
    unittest.main()
