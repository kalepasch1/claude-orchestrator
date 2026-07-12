#!/usr/bin/env python3
"""Tests for runner/postmortem.py"""
import sys, os, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import postmortem

class TestClassify(unittest.TestCase):
    def test_rollback(self):
        self.assertEqual(postmortem._classify("deployment rolled back"), "rollback")
    def test_build_failure(self):
        self.assertEqual(postmortem._classify("BUILDFAIL on master"), "build_failure")
    def test_test_failure(self):
        self.assertEqual(postmortem._classify("pytest FAILED 3"), "test_failure")
    def test_merge_conflict(self):
        self.assertEqual(postmortem._classify("HTTP Error 409: Conflict"), "merge_conflict")
    def test_timeout(self):
        self.assertEqual(postmortem._classify("read operation timed out"), "timeout")
    def test_unknown(self):
        self.assertEqual(postmortem._classify("something else"), "unknown")
    def test_empty(self):
        self.assertEqual(postmortem._classify(""), "unknown")
        self.assertEqual(postmortem._classify(None), "unknown")

class TestFingerprint(unittest.TestCase):
    def test_stable(self):
        self.assertEqual(postmortem._fingerprint("p","s","r"), postmortem._fingerprint("p","s","r"))
    def test_different(self):
        self.assertNotEqual(postmortem._fingerprint("p","a","r"), postmortem._fingerprint("p","b","r"))
    def test_length(self):
        self.assertEqual(len(postmortem._fingerprint("p","s","c")), 16)

class TestTruncate(unittest.TestCase):
    def test_short(self):
        self.assertEqual(postmortem._truncate("short"), "short")
    def test_none(self):
        self.assertEqual(postmortem._truncate(None), "")
    def test_long(self):
        r = postmortem._truncate("x" * 5000, 100)
        self.assertLessEqual(len(r), 120)
        self.assertIn("[truncated]", r)

class TestCreatePostmortem(unittest.TestCase):
    @patch("postmortem.db")
    def test_creates_record(self, mock_db):
        mock_db.upsert.return_value = {"id": "pm-1"}
        task = {"id": "t1", "slug": "my-task", "project_id": "p1", "note": "build error"}
        self.assertIsNotNone(postmortem.create_postmortem(task))
        row = mock_db.upsert.call_args[0][1]
        self.assertEqual(row["category"], "build_failure")
    @patch("postmortem.db")
    def test_handles_error(self, mock_db):
        mock_db.upsert.side_effect = Exception("net")
        self.assertIsNone(postmortem.create_postmortem({"id":"t","slug":"s","project_id":"p","note":"x"}))

class TestCreateGuardTask(unittest.TestCase):
    @patch("postmortem.db")
    def test_creates_guard(self, mock_db):
        mock_db.insert.return_value = {"id": "g1"}
        task = {"id":"t","slug":"broken","project_id":"p","note":"rolled back","base_branch":"master"}
        r = postmortem.create_guard_task(task)
        self.assertIsNotNone(r)
        row = mock_db.insert.call_args[0][1]
        self.assertTrue(row["slug"].startswith("guard-rollback-"))
        self.assertEqual(row["kind"], "bugfix")
    @patch("postmortem.db")
    def test_slug_truncation(self, mock_db):
        mock_db.insert.return_value = {"id": "g2"}
        postmortem.create_guard_task({"id":"t","slug":"a"*100,"project_id":"p","note":"fail","base_branch":"master"})
        self.assertLessEqual(len(mock_db.insert.call_args[0][1]["slug"]), 80)

class TestProcessIncident(unittest.TestCase):
    @patch("postmortem.create_guard_task")
    @patch("postmortem.create_postmortem")
    def test_full(self, mock_pm, mock_guard):
        mock_pm.return_value = {"id": "pm1"}
        mock_guard.return_value = {"id": "g1"}
        r = postmortem.process_incident({"id":"t","slug":"s","project_id":"p","note":"fail"})
        self.assertIsNotNone(r["postmortem"])
        self.assertIsNotNone(r["guard_task"])
    @patch("postmortem.create_guard_task")
    @patch("postmortem.create_postmortem")
    def test_no_guard_if_no_pm(self, mock_pm, mock_guard):
        mock_pm.return_value = None
        postmortem.process_incident({"id":"t","slug":"s","project_id":"p","note":"fail"})
        mock_guard.assert_not_called()

class TestSweep(unittest.TestCase):
    @patch("postmortem.process_incident")
    @patch("postmortem.db")
    def test_processes_blocked(self, mock_db, mock_pi):
        mock_db.select.return_value = [{"id":"t","slug":"s","project_id":"p","note":"build error","state":"BLOCKED","base_branch":"master","kind":"build"}]
        mock_pi.return_value = {"postmortem": {"id": "pm1"}, "guard_task": {"id": "g1"}}
        self.assertEqual(len(postmortem.sweep("p")), 1)
    @patch("postmortem.db")
    def test_skips_guards(self, mock_db):
        mock_db.select.return_value = [{"id":"t","slug":"s","project_id":"p","note":"auto-generated guard from postmortem of x"}]
        self.assertEqual(len(postmortem.sweep("p")), 0)

if __name__ == "__main__":
    unittest.main()
