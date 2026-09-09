#!/usr/bin/env python3
"""Tests for diff_fleet_sync — the merged-diff-memory ↔ fleet coordination bridge."""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import diff_fleet_sync


class TestBuildDigest(unittest.TestCase):
    def test_empty_merges(self):
        d = diff_fleet_sync._build_digest([])
        self.assertEqual(d["merge_count"], 0)
        self.assertEqual(d["branches"], [])
        self.assertEqual(d["top_areas"], [])
        self.assertIn("host", d)
        self.assertIn("ts", d)

    def test_extracts_branches_and_areas(self):
        merges = [
            {"branch": "agent/fix-login", "files_affected": ["runner/db.py", "runner/auth.py"]},
            {"branch": "agent/add-cache", "files_affected": ["tools/cache.py", "runner/pool.py"]},
        ]
        d = diff_fleet_sync._build_digest(merges)
        self.assertEqual(d["merge_count"], 2)
        self.assertIn("agent/fix-login", d["branches"])
        self.assertIn("agent/add-cache", d["branches"])
        # runner has 2 files, tools has 1 → runner first
        self.assertEqual(d["top_areas"][0], "runner")

    def test_caps_branches(self):
        merges = [{"branch": f"agent/b-{i}", "files_affected": []} for i in range(30)]
        d = diff_fleet_sync._build_digest(merges)
        self.assertLessEqual(len(d["branches"]), diff_fleet_sync.MAX_DIGEST_BRANCHES)

    def test_branch_name_fallback(self):
        merges = [{"branch_name": "agent/fallback", "files_affected": []}]
        d = diff_fleet_sync._build_digest(merges)
        self.assertIn("agent/fallback", d["branches"])


class TestPublishDigest(unittest.TestCase):
    @patch.object(diff_fleet_sync, "_import_db")
    @patch.object(diff_fleet_sync, "_import_merged_diff_memory")
    def test_publishes_on_success(self, mock_mdm, mock_db):
        mdm = MagicMock()
        mdm.get_recent_merges.return_value = [
            {"branch": "agent/x", "files_affected": ["runner/a.py"]}
        ]
        mock_mdm.return_value = mdm
        db = MagicMock()
        mock_db.return_value = db
        self.assertTrue(diff_fleet_sync.publish_digest())
        db.upsert.assert_called_once()
        call_args = db.upsert.call_args
        self.assertEqual(call_args[0][0], "fleet_config")
        row = call_args[0][1]
        self.assertIn(diff_fleet_sync.FLEET_KEY_PREFIX, row["key"])

    @patch.object(diff_fleet_sync, "_import_merged_diff_memory")
    def test_returns_false_on_no_merges(self, mock_mdm):
        mdm = MagicMock()
        mdm.get_recent_merges.return_value = []
        mock_mdm.return_value = mdm
        self.assertFalse(diff_fleet_sync.publish_digest())


    @patch.object(diff_fleet_sync, "_import_merged_diff_memory", return_value=None)
    def test_returns_false_on_missing_module(self, _):
        self.assertFalse(diff_fleet_sync.publish_digest())


class TestConsumeFleetDigests(unittest.TestCase):
    @patch.object(diff_fleet_sync, "_import_db")
    def test_filters_own_host(self, mock_db):
        db = MagicMock()
        db.select.return_value = [
            {"key": "ORCH_DIFF_DIGEST_other", "value": json.dumps({"host": "other-mac", "branches": ["a"]})},
            {"key": f"ORCH_DIFF_DIGEST_{diff_fleet_sync.HOST}",
             "value": json.dumps({"host": diff_fleet_sync.HOST, "branches": ["b"]})},
        ]
        mock_db.return_value = db
        result = diff_fleet_sync.consume_fleet_digests()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["host"], "other-mac")

    @patch.object(diff_fleet_sync, "_import_db", return_value=None)
    def test_returns_empty_on_no_db(self, _):
        self.assertEqual(diff_fleet_sync.consume_fleet_digests(), [])

    @patch.object(diff_fleet_sync, "_import_db")
    def test_handles_malformed_json(self, mock_db):
        db = MagicMock()
        db.select.return_value = [
            {"key": "ORCH_DIFF_DIGEST_x", "value": "not-json{"},
        ]
        mock_db.return_value = db
        self.assertEqual(diff_fleet_sync.consume_fleet_digests(), [])


class TestSync(unittest.TestCase):
    @patch.object(diff_fleet_sync, "consume_fleet_digests")
    @patch.object(diff_fleet_sync, "publish_digest")
    @patch.object(diff_fleet_sync, "_import_merged_diff_memory")
    def test_identifies_novel_branches(self, mock_mdm, mock_pub, mock_consume):
        mock_pub.return_value = True
        mock_consume.return_value = [
            {"host": "other", "branches": ["agent/new-feature", "agent/existing"]}
        ]
        mdm = MagicMock()
        mdm.get_recent_merges.return_value = [
            {"branch": "agent/existing", "files_affected": []}
        ]
        mock_mdm.return_value = mdm

        result = diff_fleet_sync.sync()
        self.assertTrue(result["published"])
        self.assertEqual(result["remote_digests"], 1)
        self.assertIn("agent/new-feature", result["novel_branches"])
        self.assertNotIn("agent/existing", result["novel_branches"])

    @patch.object(diff_fleet_sync, "consume_fleet_digests", side_effect=Exception("boom"))
    @patch.object(diff_fleet_sync, "publish_digest", return_value=False)
    def test_failsoft_on_error(self, _pub, _consume):
        result = diff_fleet_sync.sync()
        self.assertIsNotNone(result["error"])
        self.assertFalse(result["published"])


if __name__ == "__main__":
    unittest.main()
