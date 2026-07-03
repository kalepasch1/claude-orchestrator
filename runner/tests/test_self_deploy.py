"""
test_self_deploy.py - safety guards for cooperative self-deploy.

A) check_new_code reads the running commit from ORCH_BOOT_COMMIT (else the boot file)
   and flags stale only when both commits are known and differ.
B) request_restart writes the flag file + a digest notification — and NEVER hard-kills
   (no os.kill / os._exit anywhere in the module source).
C) canary_gate returns True only on rc==0 and includes --timeout=120 only when
   pytest-timeout is importable.
D) maybe_deploy: restart requested ONLY when stale AND canary passes; canary failure
   files the blocked approvals card (duplicate-index errors swallowed); never raises.
All subprocess + db calls are mocked — no network, no real pytest recursion.
"""
import os, sys, tempfile, unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import self_deploy
import db


def _proc(rc=0, out=""):
    p = MagicMock()
    p.returncode = rc
    p.stdout = out
    p.stderr = ""
    return p


class TestCheckNewCode(unittest.TestCase):

    def test_env_commit_wins_and_stale_detected(self):
        with patch.dict(os.environ, {"ORCH_BOOT_COMMIT": "aaa111"}), \
             patch.object(self_deploy.subprocess, "run",
                          return_value=_proc(0, "bbb222\n")) as run:
            st = self_deploy.check_new_code("/repo")
        self.assertEqual(st["running_commit"], "aaa111")
        self.assertEqual(st["head_commit"], "bbb222")
        self.assertTrue(st["stale"])
        # only read-only git was invoked
        self.assertEqual(run.call_args[0][0], ["git", "rev-parse", "HEAD"])

    def test_same_commit_not_stale(self):
        with patch.dict(os.environ, {"ORCH_BOOT_COMMIT": "aaa111"}), \
             patch.object(self_deploy.subprocess, "run",
                          return_value=_proc(0, "aaa111\n")):
            st = self_deploy.check_new_code("/repo")
        self.assertFalse(st["stale"])

    def test_boot_file_fallback(self):
        d = tempfile.mkdtemp()
        open(os.path.join(d, self_deploy.BOOT_FILE), "w").write("ccc333\n")
        env = {k: v for k, v in os.environ.items() if k != "ORCH_BOOT_COMMIT"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(self_deploy.subprocess, "run",
                          return_value=_proc(0, "ddd444\n")):
            st = self_deploy.check_new_code(d)
        self.assertEqual(st["running_commit"], "ccc333")
        self.assertTrue(st["stale"])

    def test_unknown_running_commit_never_stale(self):
        """No env var + no boot file -> stale must be False (never restart blindly)."""
        d = tempfile.mkdtemp()
        env = {k: v for k, v in os.environ.items() if k != "ORCH_BOOT_COMMIT"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(self_deploy.subprocess, "run",
                          return_value=_proc(0, "eee555\n")):
            st = self_deploy.check_new_code(d)
        self.assertFalse(st["stale"])


class TestRequestRestart(unittest.TestCase):

    def setUp(self):
        self.orig_flag = self_deploy.RESTART_FLAG
        self.flag = os.path.join(tempfile.mkdtemp(), ".restart_requested")
        self_deploy.RESTART_FLAG = self.flag
        self.inserts = []
        self.orig_insert = db.insert
        db.insert = lambda table, row, **kw: self.inserts.append((table, row))

    def tearDown(self):
        self_deploy.RESTART_FLAG = self.orig_flag
        db.insert = self.orig_insert

    def test_writes_flag_with_reason_and_notifies(self):
        self_deploy.request_restart("new code abc12345 passed canary gate")
        content = open(self.flag).read()
        self.assertIn("new code abc12345 passed canary gate", content)
        tables = [t for t, _ in self.inserts]
        self.assertIn("notifications", tables)
        row = dict(self.inserts)["notifications"]
        self.assertEqual(row["channel"], "digest")
        self.assertFalse(row["sent"])

    def test_notification_failure_does_not_block_flag(self):
        def _boom(*a, **kw):
            raise RuntimeError("db down")
        db.insert = _boom
        self_deploy.request_restart("reason")
        self.assertTrue(os.path.exists(self.flag), "flag must be written even if db fails")

    def test_module_never_hard_kills(self):
        """Structural: self_deploy source must not contain kill -9 / os._exit / os.kill."""
        src = open(self_deploy.__file__).read()
        self.assertNotIn("os._exit", src)
        self.assertNotIn("os.kill", src)
        self.assertNotIn("kill -9", src.replace("NO kill -9", ""))  # allow the docstring


class TestCanaryGate(unittest.TestCase):

    def test_green_suite_passes(self):
        calls = []
        def _run(cmd, **kw):
            calls.append((cmd, kw))
            return _proc(0)
        with patch.object(self_deploy.subprocess, "run", side_effect=_run):
            self.assertTrue(self_deploy.canary_gate("/repo"))
        pytest_cmd, kw = calls[-1]
        self.assertEqual(pytest_cmd[:4], ["python3", "-m", "pytest", "runner/tests"])
        self.assertIn("-x", pytest_cmd)
        self.assertEqual(kw.get("cwd"), "/repo")
        self.assertEqual(kw.get("timeout"), self_deploy.CANARY_TIMEOUT)
        self.assertIn("--timeout=120", pytest_cmd, "pytest-timeout available -> flag used")

    def test_timeout_flag_omitted_without_plugin(self):
        calls = []
        def _run(cmd, **kw):
            calls.append(cmd)
            return _proc(1 if "-c" in cmd else 0)  # import probe fails
        with patch.object(self_deploy.subprocess, "run", side_effect=_run):
            self_deploy.canary_gate("/repo")
        self.assertNotIn("--timeout=120", calls[-1])

    def test_red_suite_fails_gate(self):
        def _run(cmd, **kw):
            return _proc(0 if "-c" in cmd else 1)  # probe ok, pytest red
        with patch.object(self_deploy.subprocess, "run", side_effect=_run):
            self.assertFalse(self_deploy.canary_gate("/repo"))

    def test_subprocess_exception_fails_closed(self):
        with patch.object(self_deploy.subprocess, "run",
                          side_effect=OSError("no python3")):
            self.assertFalse(self_deploy.canary_gate("/repo"))


class TestMaybeDeploy(unittest.TestCase):

    def setUp(self):
        self.orig_flag = self_deploy.RESTART_FLAG
        self_deploy.RESTART_FLAG = os.path.join(tempfile.mkdtemp(), ".restart_requested")
        self.inserts = []
        self.orig_insert = db.insert
        db.insert = lambda table, row, **kw: self.inserts.append((table, row))

    def tearDown(self):
        self_deploy.RESTART_FLAG = self.orig_flag
        db.insert = self.orig_insert

    def test_stale_and_green_requests_restart(self):
        with patch.object(self_deploy, "check_new_code",
                          return_value={"running_commit": "a" * 40,
                                        "head_commit": "b" * 40, "stale": True}), \
             patch.object(self_deploy, "canary_gate", return_value=True):
            res = self_deploy.maybe_deploy("/repo")
        self.assertTrue(res["deployed"])
        self.assertTrue(os.path.exists(self_deploy.RESTART_FLAG))

    def test_stale_but_red_blocks_and_files_card(self):
        with patch.object(self_deploy, "check_new_code",
                          return_value={"running_commit": "a" * 40,
                                        "head_commit": "b" * 40, "stale": True}), \
             patch.object(self_deploy, "canary_gate", return_value=False):
            res = self_deploy.maybe_deploy("/repo")
        self.assertFalse(res["deployed"])
        self.assertEqual(res["reason"], "canary_failed")
        self.assertFalse(os.path.exists(self_deploy.RESTART_FLAG),
                         "restart must NOT be requested on red canary")
        cards = [r for t, r in self.inserts if t == "approvals"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["kind"], "self")
        self.assertEqual(cards[0]["title"], self_deploy.BLOCK_TITLE)

    def test_duplicate_card_index_error_ignored(self):
        def _boom(table, row, **kw):
            raise RuntimeError("HTTP 409: duplicate key value violates unique index")
        db.insert = _boom
        with patch.object(self_deploy, "check_new_code",
                          return_value={"running_commit": "a" * 40,
                                        "head_commit": "b" * 40, "stale": True}), \
             patch.object(self_deploy, "canary_gate", return_value=False):
            res = self_deploy.maybe_deploy("/repo")  # must not raise
        self.assertEqual(res["reason"], "canary_failed")

    def test_up_to_date_is_noop(self):
        with patch.object(self_deploy, "check_new_code",
                          return_value={"running_commit": "a" * 40,
                                        "head_commit": "a" * 40, "stale": False}), \
             patch.object(self_deploy, "canary_gate") as gate:
            res = self_deploy.maybe_deploy("/repo")
        self.assertFalse(res["deployed"])
        gate.assert_not_called()
        self.assertFalse(os.path.exists(self_deploy.RESTART_FLAG))

    def test_never_raises(self):
        with patch.object(self_deploy, "check_new_code",
                          side_effect=RuntimeError("git exploded")):
            res = self_deploy.maybe_deploy("/repo")
        self.assertFalse(res["deployed"])
        self.assertIn("error", res["reason"])

    def test_repo_defaults_to_parent_of_runner(self):
        seen = {}
        def _check(repo):
            seen["repo"] = repo
            return {"running_commit": "", "head_commit": "x", "stale": False}
        with patch.object(self_deploy, "check_new_code", side_effect=_check):
            self_deploy.maybe_deploy()
        expected = os.path.dirname(os.path.dirname(os.path.abspath(self_deploy.__file__)))
        self.assertEqual(seen["repo"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
