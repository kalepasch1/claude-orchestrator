#!/usr/bin/env python3
"""Tests for patch template 95fc17a356b7: template lookup by id.

patch_templates stores every built template (DB `knowledge` table, with a
fail-soft JSONL fallback at .runtime/patch_templates.jsonl) but exposed no
retrieval path — recovery/transplant flows could not resolve a stored template
back from its id. Patch 95fc17a356b7 adds `patch_templates.lookup(template_id)`:

- returns the stored template row (dict) for a known id
- checks the local JSONL fallback first, newest matching entry wins
- falls back to a best-effort DB query when the local store has no match
- fail-soft contract: returns {} for None/empty/unknown ids and on ANY
  error (missing file, corrupt lines, DB down) — never raises
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("ORCH_DB_URL", "")
os.environ.setdefault("ORCH_DB_ENABLED", "false")

import patch_templates as pt

TID = "95fc17a356b7"


def _jsonl(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write((row if isinstance(row, str) else json.dumps(row)) + "\n")


class LookupContractTest(unittest.TestCase):
    """lookup() exists and honors the fail-soft contract."""

    def test_lookup_is_exposed(self):
        self.assertTrue(callable(getattr(pt, "lookup", None)),
                        "patch_templates.lookup(template_id) must exist")

    def test_none_id_returns_empty_dict(self):
        self.assertEqual(pt.lookup(None), {})

    def test_empty_id_returns_empty_dict(self):
        self.assertEqual(pt.lookup(""), {})
        self.assertEqual(pt.lookup("   "), {})

    def test_unknown_id_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", side_effect=Exception("db down")):
                self.assertEqual(pt.lookup("ffffffffffff"), {})

    def test_never_raises_on_db_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", side_effect=RuntimeError("boom")):
                self.assertEqual(pt.lookup(TID), {})


class LookupJsonlFallbackTest(unittest.TestCase):
    """lookup() resolves templates from the local JSONL fallback store."""

    def test_known_id_found_in_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "task": "canary-claude-27-slice-3",
                           "template_id": TID, "body": f"PATCH TEMPLATE {TID}\nIntent: x"}])
            with patch.object(pt, "_fallback_path", return_value=path):
                row = pt.lookup(TID)
        self.assertEqual(row.get("template_id"), TID)
        self.assertIn(TID, row.get("body", ""))

    def test_newest_matching_entry_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [
                {"ts": 1.0, "template_id": TID, "body": "old body"},
                {"ts": 2.0, "template_id": "other0000000", "body": "unrelated"},
                {"ts": 3.0, "template_id": TID, "body": "new body"},
            ])
            with patch.object(pt, "_fallback_path", return_value=path):
                row = pt.lookup(TID)
        self.assertEqual(row.get("body"), "new body")

    def test_corrupt_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [
                "{not valid json",
                "",
                {"ts": 1.0, "template_id": TID, "body": "survives corruption"},
                "[1, 2, 3]",
            ])
            with patch.object(pt, "_fallback_path", return_value=path):
                row = pt.lookup(TID)
        self.assertEqual(row.get("body"), "survives corruption")

    def test_whitespace_around_id_is_tolerated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "template_id": TID, "body": "b"}])
            with patch.object(pt, "_fallback_path", return_value=path):
                row = pt.lookup(f"  {TID}  ")
        self.assertEqual(row.get("template_id"), TID)


class LookupDbFallbackTest(unittest.TestCase):
    """When the JSONL store has no match, lookup() tries the knowledge table."""

    def test_db_row_returned_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            db_rows = [{"title": "patch template canary", "body": f"PATCH TEMPLATE {TID}\nIntent: y"}]
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=db_rows):
                row = pt.lookup(TID)
        self.assertEqual(row.get("template_id"), TID)
        self.assertIn(TID, row.get("body", ""))

    def test_jsonl_hit_takes_precedence_over_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            _jsonl(path, [{"ts": 1.0, "template_id": TID, "body": "local wins"}])
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "select", side_effect=AssertionError("db must not be queried")):
                row = pt.lookup(TID)
        self.assertEqual(row.get("body"), "local wins")

    def test_empty_db_result_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = os.path.join(tmp, "nope.jsonl")
            with patch.object(pt, "_fallback_path", return_value=missing), \
                 patch.object(pt.db, "select", return_value=[]):
                self.assertEqual(pt.lookup(TID), {})


class StoreLookupRoundtripTest(unittest.TestCase):
    """A template written by _store() (DB down → JSONL fallback) is retrievable."""

    def test_store_then_lookup_roundtrip(self):
        task = {"slug": "canary-claude-27-slice-3", "project_id": "beethoven",
                "prompt": "write failing test for patch template lookup then verify"}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "patch_templates.jsonl")
            with patch.object(pt, "_fallback_path", return_value=path), \
                 patch.object(pt.db, "insert", side_effect=Exception("db down")), \
                 patch.object(pt.db, "select", side_effect=Exception("db down")):
                tid, body = pt.build(task)
                pt._store(task, tid, body)
                row = pt.lookup(tid)
        self.assertEqual(row.get("template_id"), tid)
        self.assertEqual(row.get("body"), body)

    def test_template_id_is_stable_12_hex(self):
        task = {"slug": "canary-claude-27-slice-3", "prompt": "same prompt"}
        tid1 = pt._id(task)
        tid2 = pt._id(dict(task))
        self.assertEqual(tid1, tid2)
        self.assertRegex(tid1, r"^[0-9a-f]{12}$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
