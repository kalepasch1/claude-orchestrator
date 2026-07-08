"""
test_merge_train.py - safety + correctness for the serialized integration train.

Everything external is mocked: db (module-level patch), git plumbing helpers, and tests.
The train must:
  A) merge a clean approved card: task -> MERGED, card -> train:MERGED
  B) skip cards already handled by the train or the legacy merge-handler, and non-merge kinds
  C) on rebase conflict under the redo cap: delete branch, requeue task with transient_retries+1,
     card -> train:redo
  D) on rebase conflict past the cap: task -> CONFLICT, card -> train:conflict-exhausted
  E) on test failure: task -> TESTFAIL, card -> train:TESTFAIL, and NEVER fast-forward the base
  F) serialize per project, oldest approval first
  G) branch-missing approved cards remain live while the task is still being rebuilt
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
            {"id": "p2", "name": "beta", "repo_path": "/tmp/fake-repo-beta",
             "default_base": "main", "test_cmd": "true"}]


class TrainCase(unittest.TestCase):
    """Shared harness: mock db + git helpers, capture db.update calls."""

    def setUp(self):
        self.updates = []          # (table, match, patch)
        self.cards = []
        self.tasks = []

        self.mock_db = MagicMock()
        self.mock_db.select.side_effect = self._select
        self.mock_db.update.side_effect = \
            lambda table, match, patch: self.updates.append((table, match, patch))

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
            slug = (params or {}).get("slug", "eq.").split("eq.", 1)[1]
            return [t for t in self.tasks if t["slug"] == slug]
        if table == "controls":
            return []
        return []

    def task_updates(self, tid):
        return [p for (tbl, m, p) in self.updates if tbl == "tasks" and m.get("id") == tid]

    def card_updates(self, cid):
        return [p for (tbl, m, p) in self.updates if tbl == "approvals" and m.get("id") == cid]


# ── A: clean merge ────────────────────────────────────────────────────────────

class TestCleanMerge(TrainCase):

    def test_approved_card_merges(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 1)
        tps = self.task_updates("t1")
        self.assertEqual(tps[0]["state"], merge_train.MERGING_STATE)
        self.assertEqual(tps[-1]["state"], "MERGED")
        cps = self.card_updates("c1")
        self.assertEqual(cps[-1]["decided_by"], "train:MERGED")
        self.assertTrue(any(tbl == "outcomes" and m.get("slug") == "feat-x" and p.get("integrated") is True
                            for tbl, m, p in self.updates))

    def test_merge_never_forced_when_tests_green_but_ff_and_rebase_used(self):
        """The train's git surface is rebase + ff only — verify both were invoked."""
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        merge_train.train_run()
        self.mocks["_rebase_onto_base"].assert_called_once()
        self.mocks["_ff_base"].assert_called_once()


# ── B: idempotency + filtering ────────────────────────────────────────────────

class TestSkipsHandledCards(TrainCase):

    def test_train_handled_card_skipped(self):
        self.cards = [_card("c1", "feat-x", decided_by="train:MERGED")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [], "already-handled card must be untouched")

    def test_merge_handler_card_skipped(self):
        self.cards = [_card("c1", "feat-x", decided_by="merge-handler:MERGED")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [])

    def test_non_merge_kind_ignored(self):
        self.cards = [_card("c1", "feat-x", kind="proposal")]
        self.tasks = [_task("t1", "feat-x")]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.updates, [])

    def test_card_without_code_merge_slug_ignored(self):
        self.cards = [{"id": "c1", "kind": "integrate", "status": "approved",
                       "decided_by": None, "title": "no slug here", "created_at": "x"}]
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.card_updates("c1"), [])


# ── G: branch-missing recovery ───────────────────────────────────────────────

class TestBranchMissing(TrainCase):

    def test_running_task_waits_without_consuming_approved_card(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="RUNNING")]
        self.mocks["_branch_exists"].return_value = False
        summary = merge_train.train_run()
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(self.task_updates("t1"), [])
        self.assertEqual(self.card_updates("c1"), [])
        self.mocks["_rebase_onto_base"].assert_not_called()

    def test_blocked_task_with_missing_branch_requeues_without_consuming_card(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", state="BLOCKED", retries=0)]
        self.mocks["_branch_exists"].return_value = False
        with patch.dict(os.environ, {"MERGE_BRANCH_MISSING_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        tp = self.task_updates("t1")[-1]
        self.assertEqual(tp["state"], "QUEUED")
        self.assertEqual(tp["transient_retries"], 1)
        self.assertEqual(self.card_updates("c1"), [])
        self.mocks["_rebase_onto_base"].assert_not_called()


# ── C/D: rebase-conflict redo pattern ─────────────────────────────────────────

class TestConflictRedo(TrainCase):

    def test_conflict_under_cap_requeues(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=0)]
        self.mocks["_rebase_onto_base"].return_value = False
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        tp = self.task_updates("t1")[-1]
        self.assertEqual(tp["state"], "QUEUED")
        self.assertEqual(tp["transient_retries"], 1)
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:redo")
        self.mocks["_delete_branch"].assert_called_once()
        self.mocks["_ff_base"].assert_not_called()

    def test_conflict_past_cap_marks_conflict(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x", retries=2)]
        self.mocks["_rebase_onto_base"].return_value = False
        with patch.dict(os.environ, {"MERGE_CONFLICT_REDO_CAP": "2"}):
            summary = merge_train.train_run()
        self.assertEqual(summary["conflict"], 1)
        self.assertEqual(self.task_updates("t1")[-1]["state"], "CONFLICT")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:conflict-exhausted")
        self.mocks["_delete_branch"].assert_not_called()


# ── E: test failures never merge ──────────────────────────────────────────────

class TestTestGate(TrainCase):

    def test_testfail_never_merges(self):
        self.cards = [_card("c1", "feat-x")]
        self.tasks = [_task("t1", "feat-x")]
        self.mocks["_run_tests"].return_value = (False, "1 test failed")
        summary = merge_train.train_run()
        self.assertEqual(summary["testfail"], 1)
        self.assertEqual(summary["merged"], 0)
        self.assertEqual(self.task_updates("t1")[-1]["state"], "TESTFAIL")
        self.assertEqual(self.card_updates("c1")[-1]["decided_by"], "train:TESTFAIL")
        self.mocks["_ff_base"].assert_not_called()
        self.mocks["_push_base"].assert_not_called()


# ── F: serialization order ────────────────────────────────────────────────────

class TestSerialization(TrainCase):

    def test_oldest_first_within_project(self):
        self.cards = [_card("c2", "feat-b", created_at="2026-01-02T00:00:00"),
                      _card("c1", "feat-a", created_at="2026-01-01T00:00:00")]
        self.tasks = [_task("t1", "feat-a"), _task("t2", "feat-b")]
        order = []
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: order.append(branch) or True
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 2)
        self.assertEqual(order, ["agent/feat-a", "agent/feat-b"],
                         "train must process oldest approval first")

    def test_low_risk_batches_before_sensitive(self):
        self.cards = [_card("c1", "pricing-auth-change", kind="material", created_at="2026-01-01T00:00:00"),
                      _card("c2", "docs-cleanup", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "pricing-auth-change"),
                      {**_task("t2", "docs-cleanup"), "kind": "docs"}]
        order = []
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: order.append(branch) or True
        summary = merge_train.train_run()
        self.assertEqual(summary["merged"], 2)
        self.assertEqual(order, ["agent/docs-cleanup", "agent/pricing-auth-change"])
        self.assertEqual(summary["risk"]["low"], 1)
        self.assertEqual(summary["risk"]["sensitive"], 1)

    def test_one_project_failure_does_not_block_other_project(self):
        self.cards = [_card("c1", "feat-a", created_at="2026-01-01T00:00:00"),
                      _card("c2", "feat-b", created_at="2026-01-02T00:00:00")]
        self.tasks = [_task("t1", "feat-a", project_id="p1"),
                      _task("t2", "feat-b", project_id="p2")]
        # p1's branch conflicts; p2's merges
        self.mocks["_rebase_onto_base"].side_effect = \
            lambda repo, branch, base: branch != "agent/feat-a"
        summary = merge_train.train_run()
        self.assertEqual(summary["redo"], 1)
        self.assertEqual(summary["merged"], 1)
        self.assertEqual(self.task_updates("t2")[-1]["state"], "MERGED")


# ── push gating ───────────────────────────────────────────────────────────────

class TestPushGate(unittest.TestCase):

    def test_push_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False), \
             patch.object(merge_train, "_git") as mock_git:
            os.environ.pop("ORCH_PUSH_ON_MERGE", None)
            err = merge_train._push_base("/repo", "main")
        self.assertEqual(err, "")
        mock_git.assert_not_called()

    def test_push_runs_when_enabled(self):
        with patch.dict(os.environ, {"ORCH_PUSH_ON_MERGE": "true"}), \
             patch.object(merge_train, "_git") as mock_git:
            mock_git.return_value = MagicMock(returncode=0, stderr="")
            err = merge_train._push_base("/repo", "main")
        self.assertEqual(err, "")
        mock_git.assert_called_once()


class TestEnsureIntegrationCard(unittest.TestCase):

    def test_creates_approved_card_once(self):
        fake = MagicMock()
        fake.select.return_value = []
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertTrue(created)
        fake.insert.assert_called_once()
        row = fake.insert.call_args.args[1]
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["slug"], "feat-x")
        self.assertEqual(row["title"], "merge of feat-x")

    def test_existing_live_card_is_not_duplicated(self):
        fake = MagicMock()
        fake.select.return_value = [_card("c1", "feat-x", decided_by=None)]
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertFalse(created)
        fake.insert.assert_not_called()

    def test_pending_existing_card_is_promoted_to_approved(self):
        fake = MagicMock()
        card = _card("c1", "feat-x", decided_by=None)
        card["status"] = "pending"
        fake.select.return_value = [card]
        with patch.object(merge_train, "db", fake):
            created = merge_train.ensure_integration_card("alpha", "feat-x")
        self.assertFalse(created)
        fake.update.assert_called_once()
        self.assertEqual(fake.update.call_args.args[2]["status"], "approved")


if __name__ == "__main__":
    unittest.main(verbosity=2)
