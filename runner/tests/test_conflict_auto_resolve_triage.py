#!/usr/bin/env python3
"""What is in conflict decides the strategy before the learned scores do.

Operator note behind this change: "The 4 failed redos rebased a remote branch whose
conflicts came from tracked .aider.* scratch files." The strategy scores in
conflict_auto_resolve are learned across every conflict in the fleet, so a conflict
confined to scratch files gets the fleet's *average* answer — rebase and rebuild —
which reproduces the identical collision every time until the redo cap is gone and the
branch parks as "needs manual rebase". Four lanes for a file nobody wanted tracked.

These tests pin the triage: scratch-only and lockfile-only conflicts are answered from
the file classes, anything touching real source still goes to the scored strategies.
"""
from __future__ import annotations

import os
import sys
import types
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RUNNER not in sys.path:
    sys.path.insert(0, RUNNER)

if "db" not in sys.modules:  # pragma: no cover - depends on test ordering
    _stub = types.ModuleType("db")
    _stub.select = lambda *a, **k: []
    _stub.update = lambda *a, **k: None
    _stub.insert = lambda *a, **k: None
    sys.modules["db"] = _stub

import conflict_auto_resolve as car  # noqa: E402


def _info(*files):
    return {"action": "block", "conflicts": [{"overlap": 0.9, "files": list(files)}]}


class ClassifyTest(unittest.TestCase):
    def test_scratch_files_are_disposable(self):
        classified = car.classify_conflict_files([
            ".aider.chat.history.md", "src/.DS_Store", "x.pyc", "logs/run.log",
            "node_modules/pkg/index.js", "__pycache__/m.cpython-39.pyc",
        ])
        self.assertEqual(classified["source"], [])
        self.assertEqual(len(classified["disposable"]), 6)

    def test_lockfiles_are_regenerable_not_disposable(self):
        classified = car.classify_conflict_files(["package-lock.json", "yarn.lock"])
        self.assertEqual(len(classified["regenerable"]), 2)
        self.assertEqual(classified["disposable"], [])

    def test_real_source_is_source(self):
        classified = car.classify_conflict_files(["runner/config_consumer.py",
                                                  "app/pages/index.vue"])
        self.assertEqual(len(classified["source"]), 2)

    def test_a_file_merely_named_like_a_log_is_not_swallowed(self):
        classified = car.classify_conflict_files(["runner/logger.py", "docs/build.md"])
        self.assertEqual(len(classified["source"]), 2, classified)

    def test_a_newline_or_comma_string_is_accepted(self):
        self.assertEqual(len(car.classify_conflict_files("a.py\nb.py")["source"]), 2)
        self.assertEqual(len(car.classify_conflict_files("a.py, b.py")["source"]), 2)

    def test_it_never_raises_on_garbage(self):
        for bad in (None, "", [], {}, 5, [None, 3, object()]):
            self.assertIsInstance(car.classify_conflict_files(bad), dict)


class TriageTest(unittest.TestCase):
    def test_scratch_only_conflict_is_answered_from_the_file_classes(self):
        result = car.triage_conflict_files([".aider.input.history"])
        self.assertIsNotNone(result)
        self.assertIn("untrack or gitignore", result["reason"])
        self.assertIn("a redo reproduces the same collision", result["reason"])

    def test_lockfile_only_conflict_says_regenerate_and_asks_first(self):
        result = car.triage_conflict_files(["package-lock.json"])
        self.assertIsNotNone(result)
        self.assertIn("regenerate", result["reason"])
        self.assertFalse(result["auto_approve"],
                         "a lockfile still changes what ships; do not auto-approve it")

    def test_any_real_source_defers_to_the_scored_strategies(self):
        self.assertIsNone(car.triage_conflict_files([".aider.tags.cache",
                                                     "runner/config_consumer.py"]))

    def test_no_files_defers(self):
        self.assertIsNone(car.triage_conflict_files([]))
        self.assertIsNone(car.triage_conflict_files(None))

    def test_the_result_carries_the_classification_for_the_directive(self):
        result = car.triage_conflict_files([".DS_Store"])
        self.assertIn("file_classes", result)
        self.assertEqual(result["file_classes"]["disposable"], [".DS_Store"])


class RecommendResolutionTest(unittest.TestCase):
    def setUp(self):
        with car._lock:
            car._resolution_log[:] = []

    def test_scratch_conflict_short_circuits_the_learned_scores(self):
        result = car.recommend_resolution(_info(".aider.chat.history.md"))
        self.assertIn("untrack or gitignore", result["reason"])
        self.assertTrue(result["auto_approve"])

    def test_source_conflict_still_gets_a_scored_strategy(self):
        result = car.recommend_resolution(_info("runner/merge_train.py"))
        self.assertIn(result["strategy"], [s["name"] for s in car.STRATEGIES])
        self.assertNotIn("untrack or gitignore", result["reason"])

    def test_no_conflict_is_unchanged(self):
        result = car.recommend_resolution({"action": "proceed"})
        self.assertEqual(result["strategy"], "none")

    def test_empty_conflict_list_is_unchanged(self):
        result = car.recommend_resolution({"action": "block", "conflicts": []})
        self.assertEqual(result["strategy"], "none")

    def test_a_conflict_payload_without_file_names_still_works(self):
        result = car.recommend_resolution({"action": "block",
                                           "conflicts": [{"overlap": 0.5}]})
        self.assertIn(result["strategy"], [s["name"] for s in car.STRATEGIES])

    def test_triaged_auto_approvals_still_respect_the_hourly_rate_limit(self):
        with car._lock:
            car._resolution_log[:] = [car.time.time()] * car.MAX_AUTO_RESOLVES_PER_HOUR
        result = car.recommend_resolution(_info(".aider.input.history"))
        self.assertFalse(result["auto_approve"],
                         "the rate limit must not be bypassed by the triage path")

    def test_recommend_never_raises_on_a_malformed_payload(self):
        for payload in (None, {}, {"conflicts": None}, {"conflicts": [None]},
                        {"conflicts": [{"files": 5}]}):
            try:
                car.recommend_resolution(payload)
            except Exception as exc:  # noqa: BLE001 — the assertion IS "no exception"
                self.fail(f"recommend_resolution raised {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    unittest.main()
