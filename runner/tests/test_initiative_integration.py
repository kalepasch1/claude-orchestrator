import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import initiative_integration as ii


def branch(slug, files=(), green=True, adds=10, dels=0):
    return ii.Branch(slug=slug, files=tuple(files), tests_green=green,
                     additions=adds, deletions=dels)


class TestInitiativeKey(unittest.TestCase):
    def test_slice_suffixes_collapse_to_one_initiative(self):
        for slug in ("feature-x", "feature-x-slice-1", "feature-x-slice-12",
                     "feature-x-shard-2", "feature-x-part-3", "feature-x-step-4"):
            self.assertEqual(ii.initiative_key(slug), "feature-x", slug)

    def test_stacked_shard_markers_collapse(self):
        """Real fleet slugs stack them: '-slice-1-slice-3'."""
        self.assertEqual(ii.initiative_key("qafix-pareto-07062319-slice-1-slice-3"),
                         "qafix-pareto-07062319")

    def test_the_agent_prefix_is_stripped(self):
        self.assertEqual(ii.initiative_key("agent/feature-x-slice-1"), "feature-x")

    def test_case_and_whitespace_are_normalised(self):
        self.assertEqual(ii.initiative_key("  Feature-X-Slice-1 "), "feature-x")

    def test_a_slug_that_is_only_a_shard_marker_is_not_emptied(self):
        self.assertTrue(ii.initiative_key("slice-1"))

    def test_empty_input_is_handled(self):
        self.assertEqual(ii.initiative_key(""), "")


class TestGrouping(unittest.TestCase):
    def test_shards_of_one_initiative_become_one_card(self):
        branches = [branch(f"feature-x-slice-{i}", [f"a{i}.py"]) for i in range(1, 5)]
        initiatives = ii.group_into_initiatives(branches)
        self.assertEqual(len(initiatives), 1)
        self.assertEqual(initiatives[0].key, "feature-x")
        self.assertEqual(len(initiatives[0].branches), 4)

    def test_distinct_initiatives_stay_separate(self):
        initiatives = ii.group_into_initiatives(
            [branch("feature-x-slice-1"), branch("feature-y-slice-1")])
        self.assertEqual([i.key for i in initiatives], ["feature-x", "feature-y"])

    def test_grouping_is_deterministic(self):
        branches = [branch("b-slice-2"), branch("a-slice-1"), branch("b-slice-1")]
        first = [i.key for i in ii.group_into_initiatives(branches)]
        second = [i.key for i in ii.group_into_initiatives(list(reversed(branches)))]
        self.assertEqual(first, second)
        self.assertEqual(first, ["a", "b"])

    def test_aggregate_diff_sums_across_shards(self):
        initiative = ii.group_into_initiatives(
            [branch("x-slice-1", ["a.py"], adds=10, dels=1),
             branch("x-slice-2", ["b.py"], adds=5, dels=2)])[0]
        self.assertEqual(initiative.additions, 15)
        self.assertEqual(initiative.deletions, 3)
        self.assertEqual(initiative.files, ["a.py", "b.py"])

    def test_collapse_ratio_reports_the_decisions_removed(self):
        branches = [branch(f"x-slice-{i}") for i in range(10)] + [branch("y")]
        report = ii.collapse_ratio(branches)
        self.assertEqual(report["decisions_before"], 11)
        self.assertEqual(report["decisions_after"], 2)
        self.assertEqual(report["removed"], 9)


class TestReadiness(unittest.TestCase):
    def test_one_red_shard_holds_the_whole_card(self):
        initiative = ii.group_into_initiatives(
            [branch("x-slice-1", green=True), branch("x-slice-2", green=False)])[0]
        state = initiative.readiness()
        self.assertFalse(state["ready"])
        self.assertEqual(state["failing"], ["x-slice-2"])

    def test_unverified_shards_are_not_treated_as_green(self):
        initiative = ii.group_into_initiatives(
            [branch("x-slice-1", green=True), branch("x-slice-2", green=None)])[0]
        state = initiative.readiness()
        self.assertFalse(state["ready"])
        self.assertEqual(state["unverified"], ["x-slice-2"])

    def test_all_green_is_ready(self):
        initiative = ii.group_into_initiatives(
            [branch("x-slice-1"), branch("x-slice-2")])[0]
        self.assertTrue(initiative.readiness()["ready"])

    def test_overlapping_files_are_surfaced_as_conflict_risk(self):
        initiative = ii.group_into_initiatives(
            [branch("x-slice-1", ["shared.py", "a.py"]),
             branch("x-slice-2", ["shared.py", "b.py"])])[0]
        self.assertEqual(initiative.overlapping_files(), ["shared.py"])

    def test_an_empty_initiative_is_not_ready(self):
        self.assertFalse(ii.Initiative("x").readiness()["ready"])


class TestDispositionMemory(unittest.TestCase):
    def test_the_same_subject_collides_under_different_slugs(self):
        """Different names, same work: the collision is the mechanism."""
        a = ii.subject_fingerprint(["runner/db.py"], "fix db")
        b = ii.subject_fingerprint(["runner/db.py"], "FIX   DB")
        self.assertEqual(a, b)

    def test_different_files_do_not_collide(self):
        self.assertNotEqual(ii.subject_fingerprint(["a.py"]),
                            ii.subject_fingerprint(["b.py"]))

    def test_file_order_does_not_change_the_fingerprint(self):
        self.assertEqual(ii.subject_fingerprint(["a.py", "b.py"]),
                         ii.subject_fingerprint(["b.py", "a.py"]))

    def test_a_merged_subject_stops_being_generated(self):
        memory = ii.DispositionMemory()
        memory.record("x-slice-1", "merged", ["runner/db.py"], "fix db")
        advice = memory.should_generate(["runner/db.py"], "fix db")
        self.assertFalse(advice["generate"])
        self.assertEqual(advice["reason"], "merged")
        self.assertEqual(advice["precedent"], "x-slice-1")

    def test_rejected_and_duplicate_also_block_generation(self):
        for kind in ("rejected", "duplicate", "superseded"):
            memory = ii.DispositionMemory()
            memory.record("s", kind, ["f.py"], "t")
            self.assertFalse(memory.should_generate(["f.py"], "t")["generate"], kind)

    def test_an_abandoned_attempt_does_NOT_veto_the_work(self):
        """One failed run must not permanently block a real piece of work."""
        memory = ii.DispositionMemory()
        memory.record("s", "abandoned", ["f.py"], "t")
        advice = memory.should_generate(["f.py"], "t")
        self.assertTrue(advice["generate"])
        self.assertIn("abandoned", advice["reason"])

    def test_an_unseen_subject_is_generated(self):
        self.assertTrue(
            ii.DispositionMemory().should_generate(["new.py"], "new")["generate"])

    def test_an_unknown_disposition_kind_is_refused(self):
        with self.assertRaises(ValueError):
            ii.DispositionMemory().record("s", "vibes", ["f.py"])

    def test_stats_summarise_the_memory(self):
        memory = ii.DispositionMemory()
        memory.record("a", "merged", ["f.py"], "t")
        memory.record("b", "duplicate", ["g.py"], "t")
        stats = memory.stats()
        self.assertEqual(stats["recorded"], 2)
        self.assertEqual(stats["by_kind"]["merged"], 1)

    def test_dedupe_flags_open_branches_already_handled(self):
        memory = ii.DispositionMemory()
        memory.record("old", "merged", ["runner/db.py"], "x-slice-1")
        flagged = ii.dedupe_candidates(
            [branch("x-slice-1", ["runner/db.py"]), branch("y", ["other.py"])], memory)
        self.assertEqual([f["slug"] for f in flagged], ["x-slice-1"])
        self.assertEqual(flagged[0]["precedent"], "old")


class TestAdvisoryOnly(unittest.TestCase):
    def test_module_exposes_no_merge_or_close_action(self):
        for forbidden in ("merge", "close_branch", "enqueue", "push", "delete"):
            self.assertFalse(hasattr(ii, forbidden), f"must not expose {forbidden}()")


if __name__ == "__main__":
    unittest.main()
