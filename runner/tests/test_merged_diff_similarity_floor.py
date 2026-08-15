#!/usr/bin/env python3
"""Wave C Part 4 retrieval floor for the merged-diff library.

The floor was 0.12, which admitted prior diffs sharing only generic orchestration
vocabulary. Those hits are still rendered into task prompts as authoritative
"SOURCE ... adapt this proven diff" blocks, so a one-paragraph specification
arrived buried in kilobytes of text describing unrelated work. Wave C Part 4
raises the floor to 0.55 and bans low-similarity priors.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import merged_diff_library as mdl  # noqa: E402

ENV_KEY = "ORCH_MERGED_DIFF_SIMILARITY_FLOOR"


def _row(slug, words, prompt="prior work"):
    return {"project": "beethoven", "slug": slug, "kind": "build",
            "prompt": prompt, "diff": "", "words": words}


class _Base(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get(ENV_KEY)
        os.environ.pop(ENV_KEY, None)

    def tearDown(self):
        if self._saved is None:
            os.environ.pop(ENV_KEY, None)
        else:
            os.environ[ENV_KEY] = self._saved


class TestFloorValue(_Base):
    def test_spec_floor_is_055(self):
        self.assertEqual(mdl.SIMILARITY_FLOOR, 0.55)

    def test_default_effective_floor_is_the_spec_floor(self):
        self.assertEqual(mdl.similarity_floor(), 0.55)

    def test_override_can_raise_the_floor(self):
        os.environ[ENV_KEY] = "0.8"
        self.assertEqual(mdl.similarity_floor(), 0.8)

    def test_override_cannot_lower_it_below_the_spec_floor(self):
        # The banned configuration: restoring the old 0.12 reopens the hijack path.
        os.environ[ENV_KEY] = "0.12"
        self.assertEqual(mdl.similarity_floor(), 0.55)

    def test_unparseable_override_falls_back(self):
        os.environ[ENV_KEY] = "not-a-number"
        self.assertEqual(mdl.similarity_floor(), 0.55)

    def test_empty_override_falls_back(self):
        os.environ[ENV_KEY] = "   "
        self.assertEqual(mdl.similarity_floor(), 0.55)

    def test_out_of_range_override_falls_back(self):
        os.environ[ENV_KEY] = "42"
        self.assertEqual(mdl.similarity_floor(), 0.55)

    def test_negative_override_falls_back(self):
        os.environ[ENV_KEY] = "-1"
        self.assertEqual(mdl.similarity_floor(), 0.55)


class TestRetrievalFiltering(_Base):
    """find() is the single choke point feeding directive(), intent_graph() and
    adapter_directive(), so the floor is asserted through it."""

    TASK = {"prompt": "alpha beta gamma delta epsilon"}

    def _find(self, rows, limit=3):
        with mock.patch.object(mdl.db, "select", return_value=rows):
            return mdl.find(self.TASK, limit=limit)

    def test_weak_neighbour_is_excluded(self):
        # Shares one word out of nine -> ~0.11, the kind of hit the old floor let in.
        rows = [_row("weak", ["alpha", "zeta", "eta", "theta", "iota"])]
        self.assertEqual(self._find(rows), [])

    def test_strong_neighbour_is_kept(self):
        rows = [_row("strong", ["alpha", "beta", "gamma", "delta", "epsilon"])]
        hits = self._find(rows)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["slug"], "strong")
        self.assertGreaterEqual(hits[0]["similarity"], 0.55)

    def test_mixed_set_keeps_only_the_strong_hit(self):
        rows = [
            _row("strong", ["alpha", "beta", "gamma", "delta", "epsilon"]),
            _row("weak", ["alpha", "zeta", "eta", "theta", "iota"]),
        ]
        self.assertEqual([h["slug"] for h in self._find(rows)], ["strong"])

    def test_every_returned_hit_meets_the_floor(self):
        rows = [
            _row("s1", ["alpha", "beta", "gamma", "delta", "epsilon"]),
            _row("s2", ["alpha", "beta", "gamma", "delta"]),
            _row("w1", ["alpha", "omega"]),
            _row("w2", ["kappa", "lambda"]),
        ]
        for hit in self._find(rows, limit=10):
            self.assertGreaterEqual(hit["similarity"], 0.55, hit["slug"])

    def test_no_qualifying_prior_yields_no_directive(self):
        # The point of the change: a task with no genuinely similar prior gets a
        # clean prompt rather than a misleading one.
        rows = [_row("weak", ["alpha", "zeta", "eta", "theta", "iota"])]
        with mock.patch.object(mdl.db, "select", return_value=rows):
            self.assertEqual(mdl.directive(self.TASK), "")
            self.assertEqual(mdl.adapter_directive(self.TASK), "")

    def test_qualifying_prior_still_produces_a_directive(self):
        rows = [_row("strong", ["alpha", "beta", "gamma", "delta", "epsilon"])]
        with mock.patch.object(mdl.db, "select", return_value=rows):
            self.assertIn("MERGED-DIFF LIBRARY", mdl.directive(self.TASK))

    def test_empty_prompt_returns_nothing(self):
        with mock.patch.object(mdl.db, "select", return_value=[]):
            self.assertEqual(mdl.find({"prompt": ""}), [])

    def test_db_failure_is_fail_soft(self):
        with mock.patch.object(mdl.db, "select", side_effect=RuntimeError("db down")):
            self.assertEqual(mdl.find(self.TASK), [])


if __name__ == "__main__":
    unittest.main()
