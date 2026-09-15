"""db_baselines: a project's posture against the fleet, from the latest snapshots."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_baselines  # noqa: E402


def snap(sid, project, score, cats, taken="2026-09-12T10:00:00+00:00"):
    return {"source_id": sid, "project": project, "taken_at": taken, "score": score,
            "counts": {"by_category": cats, "by_severity": {"high": 1}, "undermines": sum(cats.values())}}


FLEET = [
    snap("s1", "apparently-law", 40, {"security": 14, "performance": 79, "audit": 3}),
    snap("s1", "apparently-law", 99, {"security": 0}, taken="2026-09-01T00:00:00+00:00"),  # older, ignored
    snap("s2", "darwn", 70, {"security": 6, "performance": 30}),
    snap("s3", "racefeed", 65, {"security": 5, "performance": 31, "audit": 9}),
    snap("s4", "smarter", 80, {"security": 2, "performance": 10}),
    snap("s5", "smarter", 60, {"security": 4, "performance": 12}),  # second source of the same project
]


class BaselineTest(unittest.TestCase):
    def setUp(self):
        db_baselines.reset_cache()

    def test_latest_snapshot_per_source_and_project_aggregation(self):
        with patch.object(db_baselines.db, "select", lambda t, p: list(FLEET)):
            f = db_baselines.fleet()
        self.assertEqual(f["n"], 4)
        self.assertEqual(f["projects"]["apparently-law"]["score"], 40, "the older snapshot is ignored")
        self.assertEqual(f["projects"]["smarter"]["score"], 60, "worst source scores the project")
        self.assertEqual(f["projects"]["smarter"]["by_category"]["security"], 6, "sources sum")
        self.assertEqual(f["median_by_category"]["security"], 6)

    def test_baseline_ranks_and_quartiles(self):
        with patch.object(db_baselines.db, "select", lambda t, p: list(FLEET)):
            b = db_baselines.baseline("apparently-law")
            lines = db_baselines.baseline_lines("apparently-law")
        self.assertEqual(b["rank"], 4)
        self.assertEqual(b["n"], 4)
        top2 = {c["category"]: c for c in b["categories"][:2]}
        self.assertEqual(set(top2), {"performance", "security"}, "ratio to the fleet median orders the list")
        self.assertTrue(all(c["quartile"] == "worst" for c in top2.values()))
        self.assertTrue(lines and lines[0].startswith("Fleet baseline: posture 40/100, rank 4 of 4"))
        self.assertTrue(any("security gaps: 14 vs fleet median 6" in l for l in lines))

    def test_small_fleet_or_unknown_project_gives_nothing(self):
        with patch.object(db_baselines.db, "select", lambda t, p: FLEET[:3]):
            self.assertEqual(db_baselines.baseline("apparently-law"), {})
        db_baselines.reset_cache()
        with patch.object(db_baselines.db, "select", lambda t, p: list(FLEET)):
            self.assertEqual(db_baselines.baseline("nope"), {})
            self.assertEqual(db_baselines.baseline_lines(""), [])

    def test_fail_soft_and_cached(self):
        calls = []

        def boom(t, p):
            calls.append(1)
            raise RuntimeError("down")
        with patch.object(db_baselines.db, "select", boom):
            self.assertEqual(db_baselines.baseline("apparently-law"), {})
            self.assertEqual(db_baselines.baseline("apparently-law"), {})
        self.assertEqual(len(calls), 1, "one read per TTL even on failure")


if __name__ == "__main__":
    unittest.main()
