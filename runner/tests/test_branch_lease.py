import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_lease


class BranchLeaseTest(unittest.TestCase):
    def setUp(self):
        branch_lease._active.clear()
        self.task = {"id": "11111111-1111-1111-1111-111111111111",
                     "project_id": "22222222-2222-2222-2222-222222222222"}

    @mock.patch.object(branch_lease, "_sha", return_value="abc")
    @mock.patch.object(branch_lease.db, "rpc", return_value=True)
    def test_acquire_heartbeat_release_use_same_token(self, rpc, _sha):
        lease = branch_lease.acquire(self.task, "/repo", "agent/example", "main", owner="test")
        self.assertIsNotNone(lease)
        self.assertTrue(branch_lease.heartbeat(self.task["id"]))
        self.assertTrue(branch_lease.release(self.task["id"]))
        acquire_args = rpc.call_args_list[0].args[1]
        heartbeat_args = rpc.call_args_list[1].args[1]
        release_args = rpc.call_args_list[2].args[1]
        self.assertEqual(acquire_args["p_token"], heartbeat_args["p_token"])
        self.assertEqual(acquire_args["p_token"], release_args["p_token"])

    @mock.patch.object(branch_lease, "_sha", return_value=None)
    @mock.patch.object(branch_lease.db, "rpc", return_value=False)
    def test_contention_fails_closed(self, _rpc, _sha):
        self.assertIsNone(branch_lease.acquire(
            self.task, "/repo", "agent/example", "main", owner="test"))
        self.assertIsNone(branch_lease.active(self.task["id"]))

    def test_cowork_contract_forbids_destructive_branch_operations(self):
        skill = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cowork_executor", "SKILL.md")
        with open(skill, encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("git push origin HEAD:agent/{slug} --force", text)
        self.assertNotIn("git worktree add --force", text)
        self.assertNotIn(" -B agent/{slug}", text)
        self.assertIn("acquire_branch_execution_lease", text)

    def test_setup_requires_task_and_lease_identity(self):
        script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "setup-worktrees.sh")
        with open(script, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('branch lease required for ${BRANCH}', text)
        self.assertIn("refusing to overwrite worktree owned by another task", text)


if __name__ == "__main__":
    unittest.main()
