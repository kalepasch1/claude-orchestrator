#!/usr/bin/env python3
"""Tests for ops/stranded_branch_families.py.

Pure-logic: classification and totals are exercised against hand-built blob maps, so no git
repo and no network are required.
"""
import os
import sys
import unittest

OPS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, OPS)

import stranded_branch_families as fam  # noqa: E402


class FamilyKeyTests(unittest.TestCase):
    def test_strips_trailing_content_hash(self):
        self.assertEqual(fam.family_key("chatgpt-local-reconcile-beethoven-286879fa5fe4"),
                         "chatgpt-local-reconcile")

    def test_strips_slice_suffix(self):
        self.assertEqual(fam.family_key("dropbox-wave-c-thing-slice-4-do-stuff"),
                         "dropbox-wave-c")

    def test_siblings_share_a_key(self):
        a = fam.family_key("chatgpt-local-reconcile-beethoven-44d6bb63e4fc")
        b = fam.family_key("chatgpt-local-reconcile-beethoven-a92ff481c0ba")
        self.assertEqual(a, b)

    def test_handles_empty_slug(self):
        self.assertEqual(fam.family_key(""), "")


class GeneratedPathTests(unittest.TestCase):
    def test_recovery_ledger_json_is_generated(self):
        self.assertTrue(fam.is_generated("docs/recovery-ledger/286879fa5fe4.json"))

    def test_recovery_intent_txt_is_generated(self):
        self.assertTrue(fam.is_generated(".recovery-intent-canary-deepseek-6.txt"))

    def test_source_is_not_generated(self):
        self.assertFalse(fam.is_generated("runner/release_train.py"))
        self.assertFalse(fam.is_generated("docs/recovery-ledger/README.md"))

    def test_none_is_safe(self):
        self.assertFalse(fam.is_generated(None))


class ClassifyTests(unittest.TestCase):
    def test_identical_tips_are_duplicates(self):
        bm = {"a": {("f", "s1"): 10}, "b": {("f", "s1"): 10}}
        res = fam.classify(bm, {"a": "deadbeefcafe", "b": "deadbeefcafe"})
        classes = sorted(c["class"] for c in res.values())
        self.assertEqual(classes, ["distinct", "duplicate"])

    def test_strict_subset_is_subsumed(self):
        big = {("x", "s1"): 5, ("y", "s2"): 5, ("z", "s3"): 5}
        small = {("x", "s1"): 5, ("y", "s2"): 5}
        res = fam.classify({"big": big, "small": small}, {"big": "c1", "small": "c2"})
        self.assertEqual(res["small"]["class"], "subsumed")
        self.assertEqual(res["small"]["same_as"], "big")
        self.assertEqual(res["big"]["class"], "distinct")

    def test_same_path_different_blob_is_not_subsumed(self):
        """An older README is a real difference; closing on path alone would lose it."""
        big = {("README.md", "new"): 78, ("z", "s3"): 5}
        small = {("README.md", "old"): 72}
        res = fam.classify({"big": big, "small": small}, {"big": "c1", "small": "c2"})
        self.assertEqual(res["small"]["class"], "distinct")

    def test_disjoint_branches_are_both_distinct(self):
        res = fam.classify({"a": {("p", "s1"): 1}, "b": {("q", "s2"): 1}},
                           {"a": "c1", "b": "c2"})
        self.assertEqual({c["class"] for c in res.values()}, {"distinct"})

    def test_empty_branch_is_not_claimed_subsumed(self):
        res = fam.classify({"big": {("x", "s"): 1}, "empty": {}}, {"big": "c1", "empty": "c2"})
        self.assertEqual(res["empty"]["class"], "distinct")

    def test_every_branch_gets_a_reason(self):
        res = fam.classify({"a": {("p", "s"): 1}, "b": {("p", "s"): 1}},
                           {"a": "c1", "b": "c1"})
        self.assertTrue(all(v.get("why") for v in res.values()))


class TotalsTests(unittest.TestCase):
    """The batch-2 question: is a big family real work or the same bytes recounted?"""

    def setUp(self):
        # A cumulative loop: each run re-commits its predecessors' ledgers.
        self.branch_map = {
            "r3": {("docs/recovery-ledger/a.json", "la"): 100,
                   ("docs/recovery-ledger/b.json", "lb"): 100,
                   ("scripts/reconcile.mjs", "src"): 50},
            "r2": {("docs/recovery-ledger/a.json", "la"): 100,
                   ("scripts/reconcile.mjs", "src"): 50},
            "r1": {("scripts/reconcile.mjs", "src"): 50},
        }
        self.tips = {"r3": "c3", "r2": "c2", "r1": "c1"}

    def _analyze(self):
        classes = fam.classify(self.branch_map, self.tips)
        naive = sum(sum(m.values()) for m in self.branch_map.values())
        unique = {}
        for m in self.branch_map.values():
            unique.update(m)
        return classes, naive, sum(unique.values()), unique

    def test_naive_total_overstates_the_family(self):
        _c, naive, unique, _u = self._analyze()
        self.assertEqual(naive, 450)
        self.assertEqual(unique, 250)

    def test_generated_share_is_separated_from_authored(self):
        _c, _n, unique_total, unique = self._analyze()
        generated = sum(v for (p, _s), v in unique.items() if fam.is_generated(p))
        self.assertEqual(generated, 200)
        self.assertEqual(unique_total - generated, 50)

    def test_cumulative_predecessors_are_closable(self):
        classes, _n, _u, _uu = self._analyze()
        self.assertEqual(classes["r2"]["class"], "subsumed")
        self.assertEqual(classes["r1"]["class"], "subsumed")
        self.assertEqual(classes["r3"]["class"], "distinct")


class RenderTests(unittest.TestCase):
    def test_render_emits_a_markdown_table(self):
        report = {"famA": {"branches": 3, "naive_added": 450, "unique_added": 250,
                           "recounted_added": 200, "generated_added": 200,
                           "authored_added": 50, "closable": ["r1", "r2"],
                           "distinct": ["r3"], "classes": {}}}
        out = fam.render(report)
        self.assertIn("famA", out)
        self.assertIn("| 3 |", out)

    def test_render_of_empty_report_is_just_a_header(self):
        self.assertEqual(len(fam.render({}).splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
