import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import continuation_compactor


class ContinuationCompactorTest(unittest.TestCase):

    def test_compacts_many_continuations_into_one_batch_task(self):
        rows = [
            {"id": f"t{i}", "slug": f"cont-{i}", "prompt": f"continue item {i}",
             "project_id": "p1", "base_branch": "main"}
            for i in range(6)
        ]
        fake_db = MagicMock()
        fake_db.select.side_effect = [
            rows,
            [{"id": "p1", "name": "beethoven"}],
            [],
        ]

        with patch.object(continuation_compactor, "db", fake_db), \
             patch.dict(os.environ, {"ORCH_CONT_COMPACT_MIN_GROUP": "5"}, clear=False):
            out = continuation_compactor.run(limit=10)

        self.assertEqual(out["created"], 1)
        self.assertEqual(out["parked"], 6)
        inserted = fake_db.insert.call_args_list[0].args[1]
        self.assertTrue(inserted["slug"].startswith("cont-batch-beethoven-"))
        self.assertIn("Collapsed continuation shards: 6", inserted["prompt"])
        self.assertEqual(inserted["state"], "QUEUED")
        updates = [c.args[2] for c in fake_db.update.call_args_list]
        self.assertTrue(all(u["state"] == "DECOMPOSED" for u in updates))


if __name__ == "__main__":
    unittest.main()
