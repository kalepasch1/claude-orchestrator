#!/usr/bin/env python3
"""Tests for _matches_owner_calls — owner preference signal in committees.py."""
import sys, os, unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import committees


def _override(subject_title, owner_decision):
    return {"subject_title": subject_title, "owner_decision": owner_decision}


class TestMatchesOwnerCalls(unittest.TestCase):
    def test_match_returns_signal_when_owner_approved_similar_title(self):
        overrides = [_override("launch payment integration feature", "approved")]
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = overrides
            result = committees._matches_owner_calls(
                "payment integration launch", "GO: ship it"
            )
        self.assertIsNotNone(result)
        self.assertIn("matches owner's prior 'approved'", result)

    def test_contradict_returns_signal_when_stance_differs(self):
        overrides = [_override("launch payment integration feature", "approved")]
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = overrides
            result = committees._matches_owner_calls(
                "payment integration launch", "HOLD: wait for audit"
            )
        self.assertIsNotNone(result)
        self.assertIn("contradicts owner's prior 'approved'", result)

    def test_returns_none_when_no_overrides(self):
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = []
            result = committees._matches_owner_calls("anything", "GO")
        self.assertIsNone(result)

    def test_returns_none_when_insufficient_keyword_overlap(self):
        overrides = [_override("rename internal module", "approved")]
        with patch.object(committees, "db") as mdb:
            mdb.select.return_value = overrides
            result = committees._matches_owner_calls("payment integration launch", "GO")
        self.assertIsNone(result)

    def test_fail_soft_on_db_error(self):
        with patch.object(committees, "db") as mdb:
            mdb.select.side_effect = RuntimeError("db down")
            result = committees._matches_owner_calls("title", "GO")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
