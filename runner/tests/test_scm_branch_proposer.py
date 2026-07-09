"""Unit tests for scm_branch_proposer.py.

All git subprocess calls are mocked; no real repo is needed.

Acceptance scenarios:
  A. QUEUED task + missing branch          → creation proposal
  B. QUEUED task + existing branch         → no creation proposal
  C. non-QUEUED task                       → no creation proposal
  D. DONE/MERGED task + old branch         → deletion proposal
  E. DONE/MERGED task + recent branch      → no deletion proposal
  F. DONE/MERGED task + missing branch     → no deletion proposal
  G. non-terminal task + old branch        → no deletion proposal
  H. propose() combines both rule outputs
  I. heuristic disabled (env var)          → no proposals from either rule
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import scm_branch_proposer


REPO = "/fake/repo"
PROJECT = {"id": "proj-1", "repo_path": REPO, "default_base": "main"}


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


def _task(slug, state, base_branch=None, project_id="proj-1"):
    return {"id": f"id-{slug}", "slug": slug, "state": state,
            "base_branch": base_branch, "project_id": project_id}


def _ts_days_ago(days):
    import datetime
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return str(int(dt.timestamp()))


class CreationProposalTest(unittest.TestCase):
    """Rule A/B/C: propose_branch_creation."""

    def _run(self, tasks, side_effects):
        with patch("subprocess.run", side_effect=side_effects):
            return scm_branch_proposer.propose_branch_creation(tasks, PROJECT)

    def test_queued_missing_branch_proposes_create(self):
        # rev-parse fails → branch absent → proposal emitted
        result = self._run([_task("abc", "QUEUED")], [_proc(1)])
        self.assertEqual(len(result), 1)
        p = result[0]
        self.assertEqual(p["action"], "create")
        self.assertEqual(p["branch_name"], "agent/abc")
        self.assertEqual(p["project_id"], "proj-1")
        self.assertEqual(p["base"], "main")

    def test_queued_existing_branch_no_proposal(self):
        # rev-parse succeeds → branch exists → no proposal
        result = self._run([_task("abc", "QUEUED")], [_proc(0)])
        self.assertEqual(result, [])

    def test_non_queued_states_no_proposal(self):
        for state in ("RUNNING", "BLOCKED", "DONE", "MERGED", "TESTFAIL", "RETRY"):
            result = self._run([_task("abc", state)], [])
            self.assertEqual(result, [], f"unexpected proposal for state={state}")

    def test_task_base_branch_overrides_project_default(self):
        result = self._run([_task("feat", "QUEUED", base_branch="develop")], [_proc(1)])
        self.assertEqual(result[0]["base"], "develop")

    def test_project_default_base_used_when_no_task_base(self):
        proj = dict(PROJECT, default_base="master")
        with patch("subprocess.run", side_effect=[_proc(1)]):
            result = scm_branch_proposer.propose_branch_creation([_task("feat", "QUEUED")], proj)
        self.assertEqual(result[0]["base"], "master")

    def test_fallback_to_main_when_no_default(self):
        proj = {"id": "p", "repo_path": REPO}
        with patch("subprocess.run", side_effect=[_proc(1)]):
            result = scm_branch_proposer.propose_branch_creation([_task("x", "QUEUED")], proj)
        self.assertEqual(result[0]["base"], "main")

    def test_multiple_tasks_independent(self):
        tasks = [_task("a", "QUEUED"), _task("b", "QUEUED"), _task("c", "RUNNING")]
        # a: missing, b: exists, c: skipped
        with patch("subprocess.run", side_effect=[_proc(1), _proc(0)]):
            result = scm_branch_proposer.propose_branch_creation(tasks, PROJECT)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["branch_name"], "agent/a")

    def test_task_without_slug_skipped(self):
        task = {"id": "x", "state": "QUEUED", "slug": None}
        result = self._run([task], [])
        self.assertEqual(result, [])

    def test_task_without_state_skipped(self):
        task = {"id": "x", "slug": "abc"}
        result = self._run([task], [])
        self.assertEqual(result, [])

    def test_empty_task_list(self):
        result = self._run([], [])
        self.assertEqual(result, [])

    def test_repo_from_project_when_not_passed(self):
        with patch("subprocess.run", side_effect=[_proc(1)]) as m:
            scm_branch_proposer.propose_branch_creation([_task("x", "QUEUED")], PROJECT)
        call = m.call_args
        self.assertEqual(call.kwargs.get("cwd") or call.args[1] if len(call.args) > 1 else call.kwargs.get("cwd"), REPO)

    def test_repo_override_takes_precedence(self):
        other = "/other/repo"
        with patch("subprocess.run", side_effect=[_proc(1)]) as m:
            scm_branch_proposer.propose_branch_creation(
                [_task("x", "QUEUED")], PROJECT, repo=other)
        call_kwargs = m.call_args
        self.assertIn(other, str(call_kwargs))

    def test_git_error_treated_as_missing_branch(self):
        # subprocess.run throws → _git returns returncode=1 → treated as absent → proposal
        with patch("subprocess.run", side_effect=Exception("timeout")):
            result = scm_branch_proposer.propose_branch_creation([_task("x", "QUEUED")], PROJECT)
        self.assertEqual(len(result), 1)

    def test_no_repo_still_proposes_create(self):
        proj = {"id": "p"}
        result = scm_branch_proposer.propose_branch_creation([_task("x", "QUEUED")], proj)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["base"], "main")


class DeletionProposalTest(unittest.TestCase):
    """Rule D/E/F/G: propose_branch_deletion."""

    def _run(self, tasks, side_effects, retention_days=30):
        with patch("subprocess.run", side_effect=side_effects):
            return scm_branch_proposer.propose_branch_deletion(
                tasks, PROJECT, retention_days=retention_days)

    def test_done_task_old_branch_proposes_delete(self):
        age_ts = _ts_days_ago(35)
        result = self._run([_task("old", "DONE")], [_proc(0), _proc(0, stdout=age_ts)])
        self.assertEqual(len(result), 1)
        p = result[0]
        self.assertEqual(p["action"], "delete")
        self.assertEqual(p["branch_name"], "agent/old")
        self.assertIn("DONE", p["reason"])

    def test_merged_task_old_branch_proposes_delete(self):
        age_ts = _ts_days_ago(60)
        result = self._run([_task("m", "MERGED")], [_proc(0), _proc(0, stdout=age_ts)])
        self.assertEqual(len(result), 1)
        self.assertIn("MERGED", result[0]["reason"])

    def test_done_task_recent_branch_no_proposal(self):
        age_ts = _ts_days_ago(5)
        result = self._run([_task("new", "DONE")], [_proc(0), _proc(0, stdout=age_ts)])
        self.assertEqual(result, [])

    def test_done_task_one_day_over_retention_proposes(self):
        age_ts = _ts_days_ago(31)
        result = self._run([_task("over", "DONE")], [_proc(0), _proc(0, stdout=age_ts)],
                           retention_days=30)
        self.assertEqual(len(result), 1)

    def test_done_task_exactly_at_retention_no_proposal(self):
        # age == retention_days is NOT strictly older → no proposal
        age_ts = _ts_days_ago(30)
        result = self._run([_task("edge", "DONE")], [_proc(0), _proc(0, stdout=age_ts)],
                           retention_days=30)
        self.assertEqual(result, [])

    def test_done_task_missing_branch_no_proposal(self):
        # rev-parse fails → branch missing → no deletion
        result = self._run([_task("gone", "DONE")], [_proc(1)])
        self.assertEqual(result, [])

    def test_non_terminal_task_no_proposal(self):
        for state in ("QUEUED", "RUNNING", "BLOCKED", "TESTFAIL", "RETRY"):
            result = self._run([_task("x", state)], [])
            self.assertEqual(result, [], f"unexpected deletion for state={state}")

    def test_git_log_failure_no_proposal(self):
        # branch exists but git log fails → age unknown → skip
        result = self._run([_task("x", "DONE")], [_proc(0), _proc(1, stdout="")])
        self.assertEqual(result, [])

    def test_git_log_bad_output_no_proposal(self):
        result = self._run([_task("x", "DONE")], [_proc(0), _proc(0, stdout="not-a-number\n")])
        self.assertEqual(result, [])

    def test_empty_task_list(self):
        result = self._run([], [])
        self.assertEqual(result, [])

    def test_task_without_slug_skipped(self):
        task = {"id": "x", "state": "DONE", "slug": ""}
        result = self._run([task], [])
        self.assertEqual(result, [])

    def test_custom_retention_days_respected(self):
        age_ts = _ts_days_ago(10)
        result = self._run([_task("x", "DONE")], [_proc(0), _proc(0, stdout=age_ts)],
                           retention_days=7)
        self.assertEqual(len(result), 1)

    def test_multiple_tasks_mixed(self):
        # task a: DONE, old → delete; task b: DONE, recent → keep; task c: QUEUED, old → skip
        old_ts = _ts_days_ago(40)
        new_ts = _ts_days_ago(2)
        tasks = [_task("a", "DONE"), _task("b", "DONE"), _task("c", "QUEUED")]
        side = [_proc(0), _proc(0, stdout=old_ts),  # a: exists, old
                _proc(0), _proc(0, stdout=new_ts),  # b: exists, recent
                # c: QUEUED → skipped, no git calls
                ]
        with patch("subprocess.run", side_effect=side):
            result = scm_branch_proposer.propose_branch_deletion(
                tasks, PROJECT, retention_days=30)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["branch_name"], "agent/a")

    def test_no_repo_no_deletion_proposals(self):
        proj = {"id": "p"}
        age_ts = _ts_days_ago(60)
        # _branch_exists returns False when repo is empty string
        result = scm_branch_proposer.propose_branch_deletion([_task("x", "DONE")], proj,
                                                             retention_days=30)
        self.assertEqual(result, [])


class ProposeAllTest(unittest.TestCase):
    """Rule H: propose() combines both creation and deletion outputs."""

    def test_combined_returns_both(self):
        old_ts = _ts_days_ago(40)
        tasks = [_task("new-task", "QUEUED"), _task("old-task", "DONE")]
        side = [
            _proc(1),               # new-task: no branch → create proposal
            _proc(0),               # old-task: branch exists
            _proc(0, stdout=old_ts),  # old-task: age check
        ]
        with patch("subprocess.run", side_effect=side):
            result = scm_branch_proposer.propose(tasks, PROJECT, retention_days=30)
        actions = [p["action"] for p in result]
        self.assertIn("create", actions)
        self.assertIn("delete", actions)

    def test_empty_when_nothing_qualifies(self):
        tasks = [_task("x", "RUNNING")]
        with patch("subprocess.run", side_effect=[]):
            result = scm_branch_proposer.propose(tasks, PROJECT)
        self.assertEqual(result, [])


class HeuristicDisabledTest(unittest.TestCase):
    """Rule I: ORCH_SCM_BRANCH_HEURISTIC=false suppresses all proposals."""

    def setUp(self):
        self._orig = scm_branch_proposer.HEURISTIC_ENABLED
        scm_branch_proposer.HEURISTIC_ENABLED = False

    def tearDown(self):
        scm_branch_proposer.HEURISTIC_ENABLED = self._orig

    def test_creation_disabled(self):
        with patch("subprocess.run", side_effect=[_proc(1)]):
            result = scm_branch_proposer.propose_branch_creation(
                [_task("x", "QUEUED")], PROJECT)
        self.assertEqual(result, [])

    def test_deletion_disabled(self):
        old_ts = _ts_days_ago(60)
        with patch("subprocess.run", side_effect=[_proc(0), _proc(0, stdout=old_ts)]):
            result = scm_branch_proposer.propose_branch_deletion(
                [_task("x", "DONE")], PROJECT, retention_days=30)
        self.assertEqual(result, [])

    def test_propose_disabled(self):
        with patch("subprocess.run", side_effect=[]):
            result = scm_branch_proposer.propose([_task("x", "QUEUED")], PROJECT)
        self.assertEqual(result, [])


class BranchNamingTest(unittest.TestCase):
    """Branch names must follow the agent/<slug> convention (configurable prefix)."""

    def test_default_prefix_is_agent(self):
        with patch("subprocess.run", side_effect=[_proc(1)]):
            result = scm_branch_proposer.propose_branch_creation(
                [_task("my-slug", "QUEUED")], PROJECT)
        self.assertEqual(result[0]["branch_name"], "agent/my-slug")

    def test_custom_prefix_respected(self):
        orig = scm_branch_proposer.BRANCH_PREFIX
        scm_branch_proposer.BRANCH_PREFIX = "feature"
        try:
            with patch("subprocess.run", side_effect=[_proc(1)]):
                result = scm_branch_proposer.propose_branch_creation(
                    [_task("my-slug", "QUEUED")], PROJECT)
            self.assertEqual(result[0]["branch_name"], "feature/my-slug")
        finally:
            scm_branch_proposer.BRANCH_PREFIX = orig


if __name__ == "__main__":
    unittest.main()
