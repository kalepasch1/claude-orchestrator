import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import batch_mechanical


class BatchMechanicalTest(unittest.TestCase):
    def test_canaries_are_not_folded_into_mechanical_batches(self):
        rows = [
            {"id": "c1", "slug": "canary-gemini-1", "kind": "canary", "prompt": "fix typo",
             "deps": [], "project_id": "p1", "base_branch": "main"},
            {"id": "c2", "slug": "recover-missing-branch-canary-gpt-1", "kind": "canary", "prompt": "fix typo",
             "deps": [], "project_id": "p1", "base_branch": "main"},
            {"id": "m1", "slug": "doc-1", "kind": "mechanical", "prompt": "fix typo in docs",
             "deps": [], "project_id": "p1", "base_branch": "main"},
            {"id": "m2", "slug": "doc-2", "kind": "mechanical", "prompt": "fix typo in docs",
             "deps": [], "project_id": "p1", "base_branch": "main"},
            {"id": "m3", "slug": "doc-3", "kind": "mechanical", "prompt": "fix typo in docs",
             "deps": [], "project_id": "p1", "base_branch": "main"},
        ]
        db = MagicMock()
        db.select.side_effect = [rows, []]

        with patch.object(batch_mechanical, "db", db), \
             patch.object(batch_mechanical, "MIN_GROUP", 3):
            batches = batch_mechanical.find_batches()

        self.assertEqual([t["slug"] for t in batches["p1"]], ["doc-1", "doc-2", "doc-3"])


if __name__ == "__main__":
    unittest.main()
