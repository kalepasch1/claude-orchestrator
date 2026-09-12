#!/usr/bin/env python3
"""Tests for runner/scm_branch_report.py — the caller that made
scm_branch_proposer reachable. All DB access is stubbed; no network, no repo.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scm_branch_report as rep  # noqa: E402


class _FakeDB:
    """Minimal stand-in for runner/db.py's select()."""

    def __init__(self, projects=None, tasks=None, raise_on=None):
        self._projects = projects or []
        self._tasks = tasks or {}
        self._raise_on = raise_on
        self.calls = []

    def select(self, table, params):
        self.calls.append((table, params))
        if self._raise_on == table:
            raise RuntimeError(f"boom on {table}")
        if table == "projects":
            name = (params.get("name") or "").replace("eq.", "")
            if name:
                return [p for p in self._projects if p.get("name") == name]
            return list(self._projects)
        pid = (params.get("project_id") or "").replace("eq.", "")
        return list(self._tasks.get(pid, []))


class _Base(unittest.TestCase):
    def setUp(self):
        self._real_db = rep.db
        self._real_propose = rep.scm_branch_proposer.propose
        self._real_enabled = rep.REPORT_ENABLED
        rep.REPORT_ENABLED = True

    def tearDown(self):
        rep.db = self._real_db
        rep.scm_branch_proposer.propose = self._real_propose
        rep.REPORT_ENABLED = self._real_enabled

    def install(self, fake, proposals=None, propose_raises=False):
        rep.db = fake

        def _propose(tasks, project, retention_days=None):
            if propose_raises:
                raise RuntimeError("proposer exploded")
            self.last_retention = retention_days
            return list(proposals or [])

        rep.scm_branch_proposer.propose = _propose


class TestParseArgs(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(rep.parse_args([]), (None, None, False))

    def test_all_flags(self):
        self.assertEqual(
            rep.parse_args(["--project", "beethoven", "--retention-days", "7", "--json"]),
            ("beethoven", 7, True),
        )

    def test_non_numeric_retention_is_ignored_not_fatal(self):
        self.assertEqual(rep.parse_args(["--retention-days", "soon"]), (None, None, False))

    def test_unknown_args_are_skipped(self):
        self.assertEqual(rep.parse_args(["--nope", "--json"]), (None, None, True))

    def test_flag_without_value_does_not_index_error(self):
        self.assertEqual(rep.parse_args(["--project"]), (None, None, False))


class TestSummarize(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(rep.summarize(None), {"create": 0, "delete": 0, "total": 0})
        self.assertEqual(rep.summarize([]), {"create": 0, "delete": 0, "total": 0})

    def test_counts_by_action(self):
        s = rep.summarize([{"action": "create"}, {"action": "delete"}, {"action": "create"}])
        self.assertEqual(s, {"create": 2, "delete": 1, "total": 3})

    def test_unknown_action_counts_toward_total_only(self):
        s = rep.summarize([{"action": "rebase"}])
        self.assertEqual(s, {"create": 0, "delete": 0, "total": 1})


class TestFormatReport(unittest.TestCase):
    def test_empty_is_explicit_not_blank(self):
        self.assertIn("no branch proposals", rep.format_report([]))

    def test_create_line_shows_base(self):
        out = rep.format_report([{
            "action": "create", "project_name": "beethoven",
            "branch_name": "agent/x", "base": "master",
        }])
        self.assertIn("CREATE beethoven/agent/x (base master)", out)
        self.assertIn("1 proposal(s): 1 create, 0 delete", out)

    def test_delete_line_shows_reason(self):
        out = rep.format_report([{
            "action": "delete", "project_name": "beethoven",
            "branch_name": "agent/old", "reason": "terminal state (DONE), 91 days",
        }])
        self.assertIn("DELETE beethoven/agent/old", out)
        self.assertIn("91 days", out)


class TestCollectProposals(_Base):
    def _project(self, repo=None):
        return {"id": "p1", "name": "beethoven",
                "repo_path": repo or os.path.dirname(os.path.abspath(__file__)),
                "default_base": "master"}

    def test_happy_path_tags_project_name(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create", "branch_name": "agent/s", "base": "master"}])
        out = rep.collect_proposals()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["project_name"], "beethoven")

    def test_missing_repo_path_is_skipped_not_fatal(self):
        fake = _FakeDB([{"id": "p1", "name": "gone", "repo_path": "/nope/does/not/exist"}],
                       {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(), [])

    def test_empty_repo_path_is_skipped(self):
        fake = _FakeDB([{"id": "p1", "name": "gone", "repo_path": ""}], {"p1": []})
        self.install(fake, [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(), [])

    def test_project_query_failure_returns_empty(self):
        self.install(_FakeDB(raise_on="projects"), [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(), [])

    def test_task_query_failure_skips_project(self):
        fake = _FakeDB([self._project()], {}, raise_on="tasks")
        self.install(fake, [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(), [])

    def test_proposer_exception_skips_project(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, propose_raises=True)
        self.assertEqual(rep.collect_proposals(), [])

    def test_no_tasks_means_no_proposals(self):
        fake = _FakeDB([self._project()], {"p1": []})
        self.install(fake, [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(), [])

    def test_disabled_short_circuits_before_any_query(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create"}])
        rep.REPORT_ENABLED = False
        self.assertEqual(rep.collect_proposals(), [])
        self.assertEqual(fake.calls, [])

    def test_project_filter_is_passed_to_query(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create"}])
        rep.collect_proposals(project_name="beethoven")
        self.assertEqual(fake.calls[0][1].get("name"), "eq.beethoven")

    def test_project_filter_excludes_other_projects(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create"}])
        self.assertEqual(rep.collect_proposals(project_name="tomorrow"), [])

    def test_retention_days_override_reaches_proposer(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "DONE"}]})
        self.install(fake, [{"action": "delete"}])
        rep.collect_proposals(retention_days=3)
        self.assertEqual(self.last_retention, 3)

    def test_only_relevant_states_are_queried(self):
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [])
        rep.collect_proposals()
        state_filter = fake.calls[1][1]["state"]
        self.assertIn("QUEUED", state_filter)
        self.assertIn("MERGED", state_filter)
        self.assertNotIn("RUNNING", state_filter)

    def test_proposals_are_copies_not_proposer_internals(self):
        original = {"action": "create", "branch_name": "agent/s"}
        fake = _FakeDB([self._project()], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [original])
        rep.collect_proposals()
        self.assertNotIn("project_name", original)


class TestRun(_Base):
    def test_run_returns_summary(self):
        project = {"id": "p1", "name": "beethoven",
                   "repo_path": os.path.dirname(os.path.abspath(__file__))}
        fake = _FakeDB([project], {"p1": [{"slug": "s", "state": "QUEUED"}]})
        self.install(fake, [{"action": "create", "branch_name": "agent/s", "base": "master"}])
        self.assertEqual(rep.run(), {"create": 1, "delete": 0, "total": 1})

    def test_run_when_disabled_reports_disabled(self):
        rep.REPORT_ENABLED = False
        self.assertTrue(rep.run().get("disabled"))

    def test_main_exits_zero(self):
        self.install(_FakeDB([], {}), [])
        self.assertEqual(rep.main([]), 0)
        self.assertEqual(rep.main(["--json"]), 0)


if __name__ == "__main__":
    unittest.main()
