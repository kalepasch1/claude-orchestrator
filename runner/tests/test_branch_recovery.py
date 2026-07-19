import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import branch_recovery


def _proc(returncode=0, stdout="", stderr=""):
    p = MagicMock()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = stderr
    return p


REPO = "/fake/repo"


class DiagnoseTest(unittest.TestCase):
    def test_detects_local_branch(self):
        def fake_run(cmd, **kw):
            if "branch" in cmd and "--list" in cmd:
                return _proc(0, stdout="  agent/my-task\n")
            if "rev-list" in cmd:
                return _proc(0, stdout="3\n")
            return _proc(1)
        with patch("subprocess.run", side_effect=fake_run):
            result = branch_recovery.diagnose("my-task", REPO)
        self.assertEqual(result["status"], "local")
        self.assertEqual(result["action"], "push")
        self.assertIn("3 commit", result["details"])

    def test_detects_remote_branch(self):
        def fake_run(cmd, **kw):
            if "--list" in cmd:
                return _proc(0, stdout="")
            if "ls-remote" in cmd:
                return _proc(0, stdout="abc123\trefs/heads/agent/my-task")
            return _proc(1)
        with patch("subprocess.run", side_effect=fake_run):
            result = branch_recovery.diagnose("my-task", REPO)
        self.assertEqual(result["status"], "remote")
        self.assertEqual(result["action"], "fetch")

    def test_returns_gone_when_no_trace(self):
        with patch("subprocess.run", return_value=_proc(0, stdout="")):
            result = branch_recovery.diagnose("vanished-task", REPO)
        self.assertEqual(result["status"], "gone")
        self.assertEqual(result["action"], "reconstruct")


class RecoverTest(unittest.TestCase):
    def test_pushes_local_branch(self):
        def fake_run(cmd, **kw):
            if "--list" in cmd:
                return _proc(0, stdout="  agent/my-task\n")
            if "rev-list" in cmd:
                return _proc(0, stdout="1")
            if "push" in cmd:
                return _proc(0)
            return _proc(1)
        with patch("subprocess.run", side_effect=fake_run):
            result = branch_recovery.recover("my-task", REPO)
        self.assertTrue(result["recovered"])
        self.assertEqual(result["method"], "push")

    def test_returns_not_recovered_for_gone(self):
        with patch("subprocess.run", return_value=_proc(0, stdout="")):
            result = branch_recovery.recover("gone-task", REPO)
        self.assertFalse(result["recovered"])


class BatchRecoverTest(unittest.TestCase):
    def test_counts_recovered_and_failed(self):
        with patch.object(branch_recovery, "recover") as mock_recover:
            mock_recover.side_effect = [
                {"recovered": True, "method": "push", "branch": "agent/a", "details": "ok"},
                {"recovered": False, "method": "reconstruct", "branch": "agent/b", "details": "gone"},
            ]
            result = branch_recovery.batch_recover(["a", "b"], REPO)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["recovered"], 1)
        self.assertEqual(result["failed"], 1)


if __name__ == "__main__":
    unittest.main()
