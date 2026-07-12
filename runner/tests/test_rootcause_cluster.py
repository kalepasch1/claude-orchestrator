#!/usr/bin/env python3
"""Tests for runner/rootcause_cluster.py"""
import sys, os, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import rootcause_cluster

class TestClassify(unittest.TestCase):
    def test_under_specified(self):
        self.assertEqual(rootcause_cluster.classify("under-specified task")[0], "under-specified-task")
    def test_repair_loop(self):
        self.assertEqual(rootcause_cluster.classify("AGENTIC-REPAIR x AGENTIC-REPAIR y")[0], "agentic-repair-loop")
    def test_missing_branch(self):
        self.assertEqual(rootcause_cluster.classify("prior branch is missing")[0], "missing-branch")
    def test_build_tool(self):
        self.assertEqual(rootcause_cluster.classify("yarn: command not found")[0], "build-tool-missing")
    def test_merge_conflict(self):
        self.assertEqual(rootcause_cluster.classify("HTTP Error 409: Conflict")[0], "merge-conflict")
    def test_timeout(self):
        self.assertEqual(rootcause_cluster.classify("read operation timed out")[0], "timeout")
    def test_budget(self):
        self.assertEqual(rootcause_cluster.classify("budget cap exceeded")[0], "budget-blocked")
    def test_build_failure(self):
        self.assertEqual(rootcause_cluster.classify("BUILDFAIL on master")[0], "build-failure")
    def test_test_failure(self):
        self.assertEqual(rootcause_cluster.classify("pytest FAILED 3 tests")[0], "test-failure")
    def test_unclassified(self):
        n, d = rootcause_cluster.classify("random")
        self.assertEqual(n, "unclassified")
        self.assertEqual(d, "")
    def test_empty(self):
        self.assertEqual(rootcause_cluster.classify("")[0], "unclassified")
    def test_none(self):
        self.assertEqual(rootcause_cluster.classify(None)[0], "unclassified")

class TestClusterFailures(unittest.TestCase):
    @patch("rootcause_cluster.db")
    def test_groups(self, mock_db):
        mock_db.select.return_value = [
            {"id":"1","slug":"a","note":"budget cap","state":"BLOCKED"},
            {"id":"2","slug":"b","note":"budget cap","state":"BLOCKED"},
            {"id":"3","slug":"c","note":"BUILDFAIL","state":"BLOCKED"},
        ]
        c = rootcause_cluster.cluster_failures("p")
        self.assertEqual(len(c["budget-blocked"]), 2)
        self.assertEqual(len(c["build-failure"]), 1)
    @patch("rootcause_cluster.db")
    def test_error(self, mock_db):
        mock_db.select.side_effect = Exception("net")
        self.assertEqual(rootcause_cluster.cluster_failures("p"), {})

class TestCreateGuards(unittest.TestCase):
    @patch("rootcause_cluster.db")
    def test_creates_above_threshold(self, mock_db):
        mock_db.select.return_value = [{"id":str(i),"slug":f"t{i}","note":"budget cap","state":"BLOCKED"} for i in range(5)]
        mock_db.insert.return_value = {"id": "g1"}
        self.assertEqual(len(rootcause_cluster.create_cluster_guards("p")), 1)
        self.assertIn("budget-blocked", mock_db.insert.call_args[0][1]["slug"])
    @patch("rootcause_cluster.db")
    def test_skips_below(self, mock_db):
        mock_db.select.return_value = [{"id":"1","slug":"t","note":"budget cap","state":"BLOCKED"}]
        self.assertEqual(len(rootcause_cluster.create_cluster_guards("p")), 0)
    @patch("rootcause_cluster.db")
    def test_skips_unclassified(self, mock_db):
        mock_db.select.return_value = [{"id":str(i),"slug":f"t{i}","note":"random","state":"BLOCKED"} for i in range(10)]
        self.assertEqual(len(rootcause_cluster.create_cluster_guards("p")), 0)

class TestSummary(unittest.TestCase):
    @patch("rootcause_cluster.db")
    def test_report(self, mock_db):
        mock_db.select.return_value = [
            {"id":"1","slug":"a","note":"timed out","state":"BLOCKED"},
            {"id":"2","slug":"b","note":"timeout","state":"BLOCKED"},
        ]
        r = rootcause_cluster.summary("p")
        self.assertEqual(r["timeout"]["count"], 2)

class TestGuardSlug(unittest.TestCase):
    def test_truncates(self):
        self.assertLessEqual(len(rootcause_cluster._guard_slug("a"*100)), 80)
    def test_format(self):
        self.assertEqual(rootcause_cluster._guard_slug("timeout"), "guard-cluster-timeout")

if __name__ == "__main__":
    unittest.main()
