"""
test_merge_train_project_isolation.py

Per-project isolation guarantees for the merge train.  The train must process
each project independently: a failure (testfail, branch-missing, conflict) in
project A must not prevent project B from merging in the same cycle.

This complements the broader test_merge_train.py.  Only isolation-specific
scenarios live here.
"""
import os, sys, unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import merge_train


def _card(cid, slug, kind="integrate", decided_by=None, created_at="2026-01-01T00:00:00"):
    return {"id": cid, "slug": slug, "kind": kind, "status": "approved",
            "decided_by": decided_by, "created_at": created_at, "title": f"merge of {slug}"}


def _task(tid, slug, project_id="p1", state="BLOCKED", retries=0):
    return {"id": tid, "slug": slug, "project_id": project_id, "state": state,
            "transient_retries": retries, "base_branch": None}


PROJECTS = [{"id": "p1", "name": "alpha", "repo_path": "/tmp/fake-repo-alpha",
             "default_base": "main", "test_cmd": "true"},
            {"id": "p2", "name": "beta",  "repo_path": "/tmp/fake-repo-beta",
             "default_base": "main", "test_cmd": "true"}]


class IsolationCase(unittest.TestCase):
    """Shared harness identical to TrainCase in test_merge_train.py."""

    def setUp(self):
        self.updates = []
        self.cards = []
        self.tasks = []

        self.mock_db = MagicMock()
        self.mock_db.select.side_effect = self._select
        self.mock_db.update.side_effect = \
            lambda table, match, patch: self.updates.append((table, match, patch))
        self.mock_db.localize_repo_path.side_effect = lambda p: p

        patches = [
            patch.object(merge_train, "db", self.mock_db),
            patch.object(merge_train, "_branch_exists", return_value=True),
            patch.object(merge_train, "_refresh_base", return_value=None),
            patch.object(merge_train, "_rebase_onto_base", return_value=True),
            patch.object(merge_train, "_run_tests", return_value=(True, "green")),
            patch.object(merge_train, "_ff_base", return_value=True),
            patch.object(merge_train, "_push_base", return_value=""),
            patch.object(merge_train, "_delete_branch", return_value=None),
            patch.object(merge_train.approval_merge, "_free_branch", return_value=None),
            patch.object(merge_train, "_paused", return_value=False),
            patch.object(merge_train.os.path, "isdir", return_value=True),
        ]
        self.mocks = {}
        for p in patches:
            m = p.start()
            self.addCleanup(p.stop)
            name = getattr(p, "attribute", None)
            if name:
                self.mocks[name] = m

    def _select(self, table, params=None):
        if table == "approvals":
            return list(self.cards)
        if table == "projects":
            return list(PROJECTS)
        if table == "tasks":
            raw = (params or {}).get("slug", "eq.")
            if raw.startswith("in.("):
                slugs = raw[len("in.("):-1].split(",")
                return [t for t in self.tasks if t["slug"] in slugs]
            slug = raw.split("eq.", 1)[1]
            return [t for t in self.tasks if t["slug"] == slug]
        if table == "controls":
            return []
        return []

    def task_updates(self, tid):
        return [p for (tbl, m, p) in self.updates if tbl == "tasks" and m.get("id") == tid]

    def card_updates(self, cid):
        return [p for (tbl, m, p) in self.updates if tbl == "approvals" and m.get("id") == cid]


class TestTestfailIsolation(IsolationCase):

    def test_testfail_in_p1_does_not_block_p2_merge(self):
        """A test failure in project p1 must not prevent project p2 from merging."""
        self.cards = [_card("c1", "feat-a", created_at="2026-01-01T00:00:00"),
                      _card("c2", "feat-b", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "feat-a", project_id="p1"),
                      _task("t2", "feat-b", project_id="p2")]

        def fail_for_p1(repo, test_cmd):
            if "alpha" in repo:
                return (False, "1 test failed")
            return (True, "green")

        self.mocks["_run_tests"].side_effect = fail_for_p1
        summary = merge_train.train_run()

        self.assertEqual(summary["testfail"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.task_updates("t1")[-1]["state"], "TESTFAIL")
        self.assertEqual(self.task_updates("t2")[-1]["state"], "MERGED")

    def test_testfail_does_not_advance_p1_base(self):
        """After a test failure in p1, ff_base must not be called for that project."""
        self.cards = [_card("c1", "feat-a")]
        self.tasks = [_task("t1", "feat-a", project_id="p1")]
        self.mocks["_run_tests"].return_value = (False, "failure")

        merge_train.train_run()

        self.mocks["_ff_base"].assert_not_called()


class TestBranchMissingIsolation(IsolationCase):

    def test_branch_missing_in_p1_does_not_block_p2(self):
        """When p1's branch is missing, p2 should still merge successfully."""
        self.cards = [_card("c1", "feat-a", created_at="2026-01-01T00:00:00"),
                      _card("c2", "feat-b", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "feat-a", project_id="p1"),
                      _task("t2", "feat-b", project_id="p2")]

        def branch_missing_for_p1(repo, branch):
            if "alpha" in repo:
                return False
            return True

        self.mocks["_branch_exists"].side_effect = branch_missing_for_p1
        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["redo"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.task_updates("t2")[-1]["state"], "MERGED")
        # p1's card must not have been consumed
        self.assertEqual(self.card_updates("c1"), [])

    def test_running_task_branch_missing_in_p1_does_not_block_p2(self):
        """A RUNNING task whose branch vanished in p1 should not starve p2."""
        self.cards = [_card("c1", "feat-a"), _card("c2", "feat-b")]
        self.tasks = [_task("t1", "feat-a", project_id="p1", state="RUNNING"),
                      _task("t2", "feat-b", project_id="p2")]

        def branch_missing_for_p1(repo, branch):
            return "alpha" not in repo

        self.mocks["_branch_exists"].side_effect = branch_missing_for_p1
        summary = merge_train.train_run()

        self.assertEqual(summary["skipped"], 1)   # p1 waiting
        self.assertEqual(summary["merged"], 1)    # p2 unaffected


class TestConflictIsolation(IsolationCase):

    def test_rebase_conflict_in_p1_does_not_block_p2(self):
        """Rebase conflict in p1 must not prevent p2 from merging."""
        self.cards = [_card("c1", "feat-a", created_at="2026-01-01T00:00:00"),
                      _card("c2", "feat-b", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "feat-a", project_id="p1"),
                      _task("t2", "feat-b", project_id="p2")]

        def conflict_for_p1(repo, branch, base):
            return "alpha" not in repo

        self.mocks["_rebase_onto_base"].side_effect = conflict_for_p1
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()

        self.assertEqual(summary["redo"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.task_updates("t2")[-1]["state"], "MERGED")


class TestPerProjectOrdering(IsolationCase):

    def test_each_project_orders_by_oldest_approval(self):
        """Oldest-first ordering must be applied independently per project."""
        self.cards = [
            _card("c1", "feat-a1", created_at="2026-01-02T00:00:00"),
            _card("c2", "feat-a2", created_at="2026-01-01T00:00:00"),
            _card("c3", "feat-b1", created_at="2026-01-04T00:00:00"),
            _card("c4", "feat-b2", created_at="2026-01-03T00:00:00"),
        ]
        self.tasks = [
            _task("t1", "feat-a1", project_id="p1"),
            _task("t2", "feat-a2", project_id="p1"),
            _task("t3", "feat-b1", project_id="p2"),
            _task("t4", "feat-b2", project_id="p2"),
        ]
        order = []
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: order.append(branch) or True

        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 4)

        # Within each project: oldest card first
        p1_order = [b for b in order if "feat-a" in b]
        p2_order = [b for b in order if "feat-b" in b]
        self.assertEqual(p1_order, ["agent/feat-a2", "agent/feat-a1"])
        self.assertEqual(p2_order, ["agent/feat-b2", "agent/feat-b1"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
