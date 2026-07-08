import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backlog_compactor


class BacklogCompactorTest(unittest.TestCase):

    def test_compacts_stale_other_tasks_and_protects_release_work(self):
        rows = [
            {"id": f"t{i}", "slug": f"old-{i}", "prompt": f"old task {i}",
             "project_id": "p1", "base_branch": "main", "deps": [], "material": False}
            for i in range(9)
        ] + [
            {"id": "r1", "slug": "qafix-app", "prompt": "fix release",
             "project_id": "p1", "base_branch": "main", "deps": [], "material": False}
        ]
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            rows,
            [{"id": "p1", "name": "beethoven"}],
            [],
        ]

        with patch.object(backlog_compactor, "db", fake_db), \
             patch.dict(os.environ, {"ORCH_BACKLOG_COMPACT_MIN_GROUP": "8"}, clear=False):
            out = backlog_compactor.run(limit=20)

        self.assertEqual(out["created"], 1)
        self.assertEqual(out["parked"], 9)
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertTrue(inserted["slug"].startswith("backlog-batch-beethoven-"))
        self.assertIn("Collapsed queued tasks: 9", inserted["prompt"])
        updates = [c.args[2] for c in fake_db.update.call_args_list]
        self.assertTrue(all(u["state"] == "DECOMPOSED" for u in updates))


if __name__ == "__main__":
    unittest.main()
