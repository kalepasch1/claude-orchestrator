import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import route_evidence


class RouteEvidenceTest(unittest.TestCase):

    def test_backfill_marks_existing_outcome_integrated(self):
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "t1", "slug": "merged-x", "kind": "build", "model": "codex:sonnet",
              "force_coder": "codex", "state": "MERGED", "attempt": 1}],
            [{"id": "o1", "slug": "merged-x", "integrated": False, "tests_passed": False,
              "model": "codex:sonnet"}],
        ]
        updates = []
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(route_evidence, "db", db):
            out = route_evidence.backfill_merged()

        self.assertEqual(out["updated"], 1)
        self.assertEqual(updates[0][0], "outcomes")
        self.assertEqual(updates[0][1], {"id": "o1"})
        self.assertTrue(updates[0][2]["integrated"])
        self.assertTrue(updates[0][2]["tests_passed"])

    def test_backfill_inserts_missing_outcome_with_forced_coder_model(self):
        inserted = []
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "t2", "slug": "merged-y", "kind": "canary", "model": "claude-sonnet-4-6",
              "force_coder": "ollama", "state": "MERGED", "attempt": 2}],
            [],
            [],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))

        with patch.object(route_evidence, "db", db):
            out = route_evidence.backfill_merged()

        self.assertEqual(out["inserted"], 1)
        row = inserted[0][1]
        self.assertEqual(row["slug"], "merged-y")
        self.assertEqual(row["model"], "ollama:claude-sonnet-4-6")
        self.assertTrue(row["integrated"])
        self.assertTrue(row["tests_passed"])
        self.assertEqual(row["note"], route_evidence.BACKFILL_NOTE)

    def test_backfill_checks_slug_when_initial_window_misses_existing(self):
        inserted = []
        updates = []
        db = MagicMock()
        db.select.side_effect = [
            [{"id": "t3", "slug": "merged-z", "kind": "build", "model": "claude-sonnet-4-6",
              "force_coder": "codex", "state": "MERGED", "attempt": 1}],
            [],
            [{"id": "o3", "slug": "merged-z", "integrated": False, "tests_passed": False,
              "model": "codex:claude-sonnet-4-6"}],
        ]
        db.insert.side_effect = lambda table, row: inserted.append((table, row))
        db.update.side_effect = lambda table, match, patch: updates.append((table, match, patch))

        with patch.object(route_evidence, "db", db):
            out = route_evidence.backfill_merged()

        self.assertEqual(out["inserted"], 0)
        self.assertEqual(out["updated"], 1)
        self.assertEqual(inserted, [])
        self.assertIn("slug", db.select.call_args_list[2][0][1])

    def test_dedupe_attribution_rows_collapses_repeated_backfill_only(self):
        rows = [
            {"slug": "same", "model": "ollama:m", "kind": "build", "integrated": True,
             "tests_passed": True, "usd": 0, "wall_ms": 0},
            {"slug": "same", "model": "ollama:m", "kind": "build", "integrated": True,
             "tests_passed": True, "usd": 0, "wall_ms": 0},
            {"slug": "same", "model": "ollama:m", "kind": "build", "integrated": False,
             "tests_passed": True, "usd": 0.01, "wall_ms": 1000},
        ]

        out = route_evidence.dedupe_attribution_rows(rows)

        self.assertEqual(len(out), 2)
        self.assertFalse(out[-1]["integrated"])

    def test_stock_canaries_when_non_claude_evidence_below_target(self):
        fake_canary = types.SimpleNamespace(run=lambda limit_per_coder=1: {"queued": 3})
        summary = {"claude": {"tested": 100, "merged": 10}, "codex": {"tested": 1, "merged": 0}}
        with patch.dict(sys.modules, {"coder_canary": fake_canary}), \
             patch.object(route_evidence, "_target_coders", return_value=["codex"]), \
             patch.object(route_evidence, "TARGET_NON_CLAUDE_TESTED", 10), \
             patch.object(route_evidence, "TARGET_NON_CLAUDE_MERGED", 5):
            out = route_evidence.stock_canaries(summary)
        self.assertEqual(out["queued"], 3)
        self.assertEqual(out["tested"], 1)
        self.assertEqual(out["merged"], 0)

    def test_stock_canaries_requires_each_configured_coder(self):
        fake_canary = types.SimpleNamespace(run=lambda limit_per_coder=1: {"queued": 0})
        summary = {
            "claude": {"tested": 100, "merged": 10},
            "ollama": {"tested": 50, "merged": 20},
            "codex": {"tested": 20, "merged": 10},
        }
        with patch.dict(sys.modules, {"coder_canary": fake_canary}), \
             patch.object(route_evidence, "_target_coders", return_value=["ollama", "codex", "gemini", "gpt", "deepseek"]), \
             patch.object(route_evidence, "TARGET_NON_CLAUDE_TESTED", 10), \
             patch.object(route_evidence, "TARGET_NON_CLAUDE_MERGED", 5), \
             patch.object(route_evidence, "TARGET_TESTED_PER_CODER", 2), \
             patch.object(route_evidence, "TARGET_MERGED_PER_CODER", 1):
            out = route_evidence.stock_canaries(summary)
        self.assertEqual(out["reason"], "per_coder_evidence_gap")
        self.assertEqual(set(out["missing_coders"]), {"gemini", "gpt", "deepseek"})


if __name__ == "__main__":
    unittest.main()
