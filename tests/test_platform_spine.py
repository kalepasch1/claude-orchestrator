#!/usr/bin/env python3
"""Wave C slice 3 — cross-app (Part 6) and pipeline (Part 7) contracts."""
import os
import sys
import unittest

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import platform_spine as ps  # noqa: E402


class MatterKeyTests(unittest.TestCase):
    def test_the_same_matter_yields_the_same_key_from_any_app(self):
        a = ps.matter_key("Tomorrow Inc", "MTL analysis", "us-ca")
        b = ps.matter_key("  tomorrow inc ", "MTL Analysis", "US-CA")
        self.assertTrue(a)
        self.assertEqual(a, b, "the key must be derived, not allocated — three apps that have "
                              "never spoken must agree")

    def test_different_matters_do_not_collide(self):
        self.assertNotEqual(ps.matter_key("Org", "MTL", "us-ca"),
                            ps.matter_key("Org", "MTL", "us-ny"))
        self.assertNotEqual(ps.matter_key("Org", "MTL", "us-ca"),
                            ps.matter_key("Other", "MTL", "us-ca"))

    def test_an_unidentifiable_matter_yields_an_empty_key_not_a_colliding_one(self):
        for args in ((None, None, None), ("", "subject", "us"), ("org", "", "us")):
            self.assertEqual(ps.matter_key(*args), "", repr(args))

    def test_the_key_is_readable_enough_to_debug(self):
        self.assertTrue(ps.matter_key("Tomorrow", "x", "us").startswith("m-tomorrow-"))


class MatterSpineTests(unittest.TestCase):
    def test_an_artifact_attaches_to_a_matter(self):
        edge = ps.attach("m-x", "filing", "f-1")
        self.assertEqual(edge, {"matter": "m-x", "type": "filing", "id": "f-1"})

    def test_every_declared_artifact_type_is_attachable(self):
        for artifact in ps.MATTER_ARTIFACTS:
            self.assertIsNotNone(ps.attach("m-x", artifact, "id"), artifact)

    def test_an_unknown_artifact_type_is_refused(self):
        self.assertIsNone(ps.attach("m-x", "spreadsheet", "id"))

    def test_attach_is_fail_soft(self):
        self.assertIsNone(ps.attach("", "filing", "f"))
        self.assertIsNone(ps.attach("m", "filing", None))

    def test_three_views_of_one_matter_agree(self):
        key = ps.matter_key("Org", "MTL", "us-ca")
        result = ps.views_agree({v: {"matter": key} for v in ps.MATTER_VIEWS})
        self.assertTrue(result["agree"])
        self.assertEqual(result["matters"], [key])

    def test_three_views_of_three_matters_is_the_part_6_problem(self):
        result = ps.views_agree({
            "inbox": {"matter": "m-a"},
            "portal": {"matter": "m-b"},
            "exposure": {"matter": "m-c"},
        })
        self.assertFalse(result["agree"])
        self.assertEqual(len(result["matters"]), 3)
        self.assertIn("three systems, three different matters", result["reason"])

    def test_a_view_with_no_key_is_named_as_unreconcilable(self):
        result = ps.views_agree({"inbox": {"matter": "m-a"}, "portal": {}})
        self.assertFalse(result["agree"])
        self.assertIn("exposure", result["missing_views"])
        self.assertIn("cannot be reconciled", result["reason"])

    def test_views_agree_is_fail_soft(self):
        self.assertFalse(ps.views_agree(None)["agree"])
        self.assertFalse(ps.views_agree({"inbox": "junk"})["agree"])


class HedgeFlywheelTests(unittest.TestCase):
    EXPOSURES = [
        {"id": "e1", "expected_loss_usd": 600_000, "hedgeable": True, "instrument": "TMR-MTL"},
        {"id": "e2", "expected_loss_usd": 300_000, "hedgeable": False},
        {"id": "e3", "expected_loss_usd": 100_000, "hedgeable": True},   # no instrument named
    ]

    def test_the_ratio_is_the_headline_number(self):
        report = ps.hedge_flywheel(self.EXPOSURES)
        self.assertEqual(report["quantified_usd"], 1_000_000)
        self.assertEqual(report["hedgeable_usd"], 600_000)
        self.assertEqual(report["hedgeable_ratio"], 0.6)

    def test_hedgeable_without_a_named_instrument_does_not_count(self):
        """A claim that it is hedgeable is not an instrument anyone can buy."""
        report = ps.hedge_flywheel(self.EXPOSURES)
        self.assertIn("e3", [item["id"] for item in report["foundry_backlog"]])
        self.assertEqual(report["unhedgeable_usd"], 400_000)

    def test_the_unhedgeable_remainder_is_returned_as_a_backlog_not_summarised_away(self):
        backlog = ps.hedge_flywheel(self.EXPOSURES)["foundry_backlog"]
        self.assertEqual([item["id"] for item in backlog], ["e2", "e3"])
        for item in backlog:
            self.assertTrue(item["reason"])

    def test_the_backlog_is_ranked_by_size(self):
        backlog = ps.hedge_flywheel(self.EXPOSURES)["foundry_backlog"]
        self.assertGreaterEqual(backlog[0]["expected_loss_usd"], backlog[-1]["expected_loss_usd"])

    def test_unquantified_exposure_is_counted_separately_not_silently_dropped(self):
        report = ps.hedge_flywheel([
            {"id": "a", "expected_loss_usd": None},
            {"id": "b", "expected_loss_usd": "not a number"},
            {"id": "c", "expected_loss_usd": 0},
            {"id": "d", "expected_loss_usd": 100, "hedgeable": True, "instrument": "x"},
        ])
        self.assertEqual(report["unquantified"], 3)
        self.assertEqual(report["quantified_usd"], 100)

    def test_no_exposures_yields_no_ratio_rather_than_a_misleading_zero(self):
        self.assertIsNone(ps.hedge_flywheel([])["hedgeable_ratio"])

    def test_flywheel_is_fail_soft(self):
        self.assertEqual(ps.hedge_flywheel(None)["quantified_usd"], 0)
        self.assertEqual(ps.hedge_flywheel(["junk", None])["quantified_usd"], 0)

    def test_render_names_the_foundry_backlog(self):
        self.assertIn("instrument-foundry backlog", ps.render(ps.hedge_flywheel(self.EXPOSURES)))


class RenewalAnnuityTests(unittest.TestCase):
    FILING = {
        "id": "f-1", "matter": "m-1",
        "effective_at": "2026-01-01T00:00:00+00:00",
        "renewal_months": 12, "report_months": 3,
    }

    def test_a_filing_schedules_its_own_renewals_and_reports(self):
        schedule = ps.renewal_schedule(self.FILING, horizon_years=1)
        kinds = {entry["kind"] for entry in schedule}
        self.assertEqual(kinds, {"renewal", "report"})
        self.assertEqual(len([e for e in schedule if e["kind"] == "report"]), 4)

    def test_every_entry_gives_the_monitor_a_head_start(self):
        for entry in ps.renewal_schedule(self.FILING, horizon_years=1):
            self.assertLess(entry["watch_from"], entry["due_at"],
                            "a due date with no lead time is a date someone must remember")

    def test_the_schedule_is_ordered_by_due_date(self):
        schedule = ps.renewal_schedule(self.FILING, horizon_years=2)
        self.assertEqual([e["due_at"] for e in schedule],
                         sorted(e["due_at"] for e in schedule))

    def test_entries_carry_the_matter_so_the_spine_stays_intact(self):
        for entry in ps.renewal_schedule(self.FILING, horizon_years=1):
            self.assertEqual(entry["matter"], "m-1")
            self.assertEqual(entry["filing_id"], "f-1")

    def test_the_horizon_bounds_the_schedule(self):
        one = ps.renewal_schedule(self.FILING, horizon_years=1)
        three = ps.renewal_schedule(self.FILING, horizon_years=3)
        self.assertGreater(len(three), len(one))

    def test_a_filing_with_no_cadence_schedules_nothing(self):
        self.assertEqual(ps.renewal_schedule({"effective_at": "2026-01-01T00:00:00+00:00"}), [])

    def test_a_filing_with_no_or_bad_effective_date_is_fail_soft(self):
        self.assertEqual(ps.renewal_schedule({"renewal_months": 12}), [])
        self.assertEqual(ps.renewal_schedule({"effective_at": "nope", "renewal_months": 12}), [])
        self.assertEqual(ps.renewal_schedule(None), [])


class InitiativeMergeUnitTests(unittest.TestCase):
    BRANCHES = [
        {"slug": "fleet-immune-system-contracts", "ready": True},
        {"slug": "fleet-immune-system-slice-2", "ready": True},
        {"slug": "fleet-immune-system-slice-3", "ready": False},
        {"slug": "video-hub-slice-1", "ready": True},
    ]

    def test_slices_of_one_initiative_collapse_to_one_card(self):
        grouped = ps.group_into_initiatives(self.BRANCHES)
        self.assertEqual(len(grouped), 2)
        self.assertEqual(len(grouped["fleet-immune-system"]["branches"]), 3)

    def test_an_initiative_is_ready_only_when_every_branch_is(self):
        grouped = ps.group_into_initiatives(self.BRANCHES)
        self.assertFalse(grouped["fleet-immune-system"]["ready"])
        self.assertIn("fleet-immune-system-slice-3", grouped["fleet-immune-system"]["blocked_by"])
        self.assertTrue(grouped["video-hub"]["ready"])

    def test_the_collapse_ratio_shows_the_saving(self):
        self.assertEqual(ps.collapse_ratio(self.BRANCHES), 0.5)

    def test_initiative_is_recovered_from_the_slug_alone(self):
        for slug, expected in (
            ("wave-c-codegen-slice-2", "wave-c-codegen"),
            ("wave-c-codegen-group-11", "wave-c-codegen"),
            # The contracts shard belongs to its initiative: every sibling depends on it, so
            # judging it as its own card splits the changeset this function exists to keep whole.
            ("wave-c-codegen-contracts", "wave-c-codegen"),
            ("plain-slug", "plain-slug"),
        ):
            self.assertEqual(ps.initiative_of(slug), expected, slug)

    def test_stacked_suffixes_are_stripped(self):
        self.assertEqual(ps.initiative_of("x-y-slice-2-attempt-1"), "x-y")

    def test_blockers_are_aggregated_across_the_initiative(self):
        grouped = ps.group_into_initiatives([
            {"slug": "a-slice-1", "ready": True, "blocked_by": ["external-dep"]},
            {"slug": "a-slice-2", "ready": True},
        ])
        self.assertIn("external-dep", grouped["a"]["blocked_by"])

    def test_grouping_is_fail_soft(self):
        self.assertEqual(ps.group_into_initiatives(None), {})
        self.assertEqual(ps.group_into_initiatives([None, {}, "x"]), {})
        self.assertIsNone(ps.collapse_ratio([]))


class DispositionMemoryTests(unittest.TestCase):
    CLOSURES = [
        {"slug": "spam-initiative-slice-1", "disposition": "duplicate"},
        {"slug": "spam-initiative-slice-2", "disposition": "superseded"},
        {"slug": "spam-initiative-slice-3", "disposition": "already-done"},
        {"slug": "good-initiative-slice-1", "disposition": "merged"},
        {"slug": "one-off-slice-1", "disposition": "duplicate"},
    ]

    def test_an_initiative_that_keeps_producing_duplicates_is_suppressed(self):
        signal = ps.disposition_signal(self.CLOSURES)
        self.assertIn("spam-initiative", signal["suppress"])

    def test_a_healthy_initiative_is_never_suppressed(self):
        self.assertNotIn("good-initiative", ps.disposition_signal(self.CLOSURES)["suppress"])

    def test_a_single_bad_shard_does_not_suppress_a_whole_initiative(self):
        self.assertNotIn("one-off", ps.disposition_signal(self.CLOSURES)["suppress"])

    def test_the_waste_ratio_is_reported(self):
        signal = ps.disposition_signal(self.CLOSURES)
        self.assertEqual(signal["total"], 5)
        self.assertEqual(signal["wasted"], 4)
        self.assertEqual(signal["waste_ratio"], 0.8)

    def test_the_planner_is_told_not_to_generate_more_of_it(self):
        signal = ps.disposition_signal(self.CLOSURES)
        allowed, reason = ps.should_generate("spam-initiative-slice-9", signal)
        self.assertFalse(allowed)
        self.assertIn("already decided was not worth doing", reason)
        self.assertIn("duplicate", reason)

    def test_unrelated_new_work_is_still_generated(self):
        signal = ps.disposition_signal(self.CLOSURES)
        allowed, reason = ps.should_generate("brand-new-initiative-slice-1", signal)
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_the_reasons_are_itemised_so_the_suppression_is_reviewable(self):
        bucket = ps.disposition_signal(self.CLOSURES)["by_initiative"]["spam-initiative"]
        self.assertEqual(bucket["count"], 3)
        self.assertEqual(set(bucket["reasons"]), {"duplicate", "superseded", "already-done"})
        self.assertEqual(len(bucket["slugs"]), 3)

    def test_the_threshold_is_adjustable(self):
        self.assertIn("one-off",
                      ps.disposition_signal(self.CLOSURES, min_occurrences=1)["suppress"])

    def test_disposition_memory_is_fail_soft(self):
        self.assertEqual(ps.disposition_signal(None)["suppress"], [])
        self.assertEqual(ps.disposition_signal(["junk", None])["total"], 0)
        self.assertTrue(ps.should_generate("x", None)[0])
        self.assertTrue(ps.should_generate(None, {})[0])

    def test_render_names_what_will_be_suppressed(self):
        self.assertIn("SUPPRESS spam-initiative", ps.render(ps.disposition_signal(self.CLOSURES)))


if __name__ == "__main__":
    unittest.main()
