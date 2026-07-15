import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import control_plane
import portfolio_planner


class ControlPlaneTests(unittest.TestCase):
    def test_fingerprint_ignores_slug_and_run_date(self):
        a = {"project_id": "p", "kind": "build", "slug": "improve-a-20260714",
             "prompt": "Improve branch recovery run 2026-07-14 id 123456"}
        b = {"project_id": "p", "kind": "build", "slug": "improve-b-20261008",
             "prompt": "Improve branch recovery run 2026-10-08 id 999999"}
        self.assertEqual(control_plane.objective_fingerprint(a), control_plane.objective_fingerprint(b))

    def test_evidence_fingerprint_preserves_model_identity(self):
        base = {"project_id": "p", "kind": "canary", "slug": "canary-x",
                "prompt": "Verify the same bounded change"}
        self.assertNotEqual(
            control_plane.objective_fingerprint({**base, "model": "gpt"}),
            control_plane.objective_fingerprint({**base, "model": "gemini"}),
        )

    def test_liquidation_blocks_generator_but_not_delivery(self):
        with mock.patch.dict(os.environ, {"ORCH_LIQUIDATION_MODE": "true"}):
            idea = control_plane.prepare_task({
                "project_id": "p", "slug": "improve-more-things", "kind": "build",
                "prompt": "Add another speculative improvement to orchestration behavior",
            })
            fix = control_plane.prepare_task({
                "project_id": "p", "slug": "deployfix-prod", "kind": "bugfix",
                "prompt": "Repair the failing production deployment and verify the release",
            })
        self.assertFalse(idea["accept"])
        self.assertTrue(fix["accept"])
        self.assertIn("outcome:", fix["row"]["note"])

    def test_semantic_duplicate_is_rejected(self):
        existing = [{"id": "1", "slug": "old", "prompt": "Implement safe webhook retry backoff",
                     "note": "", "state": "QUEUED", "project_id": "p"}]
        with mock.patch.dict(os.environ, {"ORCH_LIQUIDATION_MODE": "false",
                                          "ORCH_ADMISSION_SIMILARITY": "0.80"}):
            result = control_plane.prepare_task({
                "project_id": "p", "slug": "new", "kind": "build",
                "prompt": "Implement safe webhook retry backoff",
            }, select_fn=lambda *_args, **_kwargs: existing)
        self.assertFalse(result["accept"])
        self.assertEqual(result["existing"][0]["id"], "1")

    def test_schedule_compiler_removes_duplicate_jobs(self):
        schedule = [
            ("a", "job.py", "daily", (4, 0)),
            ("b", "job.py", "interval", 600),
            ("c", "other.py", "interval", 900),
            ("d", "job.py", "interval", 300),
        ]
        out = control_plane.normalize_schedule(schedule)
        self.assertEqual(len(out), 2)
        self.assertEqual(next(x for x in out if x[1] == "job.py")[3], 300)

    def test_portfolio_plan_avoids_file_conflicts(self):
        tasks = [
            {"id": "a", "project_id": "p", "slug": "deployfix-a", "kind": "bugfix",
             "prompt": "Fix runner/db.py safely", "priority": 1},
            {"id": "b", "project_id": "p", "slug": "feature-b", "kind": "build",
             "prompt": "Refactor runner/db.py for speed", "priority": 2},
            {"id": "c", "project_id": "q", "slug": "feature-c", "kind": "build",
             "prompt": "Update web/pages/index.vue", "priority": 3},
        ]
        result = portfolio_planner.plan(tasks, 3)
        ids = {t["id"] for t in result["selected"]}
        self.assertIn("a", ids)
        self.assertIn("c", ids)
        self.assertNotIn("b", ids)
        self.assertEqual(result["reasons"]["b"], "predicted-file-conflict")


if __name__ == "__main__":
    unittest.main()
