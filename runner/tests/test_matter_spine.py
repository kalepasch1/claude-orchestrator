import os
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matter_spine as ms

FILED = date(2026, 1, 15)


def spine_with_matter(matter_id="m1"):
    spine = ms.MatterSpine()
    spine.open_matter(matter_id, title="Acme licensing")
    return spine


class TestMatterSpine(unittest.TestCase):
    def test_three_views_are_projections_of_one_truth(self):
        spine = spine_with_matter()
        spine.attach_filing(ms.Filing("f1", "m1", "licence", FILED, "annual"))
        spine.attach_exposure(ms.Exposure("e1", "m1", 1000.0, True))
        views = spine.all_views("m1")
        self.assertEqual(sorted(views), ["exposure", "inbox", "portal"])
        # One truth: the digest is identical across all three.
        self.assertTrue(spine.views_agree("m1"))

    def test_a_change_moves_every_view_together(self):
        spine = spine_with_matter()
        before = spine.view("inbox", "m1")["digest"]
        spine.attach_filing(ms.Filing("f1", "m1", "licence", FILED))
        after = spine.all_views("m1")
        self.assertNotEqual(after["inbox"]["digest"], before)
        self.assertTrue(spine.views_agree("m1"))

    def test_every_artifact_type_keys_to_the_same_matter(self):
        spine = spine_with_matter()
        for kind in ("video", "newsletter", "filing_packet", "correspondence"):
            spine.attach_artifact("m1", kind, f"ref-{kind}")
        portal = spine.view("portal", "m1")
        self.assertEqual(len(portal["artifacts"]), 4)

    def test_attaching_to_an_unknown_matter_is_refused(self):
        spine = ms.MatterSpine()
        with self.assertRaises(ms.MatterIntegrityError):
            spine.attach_filing(ms.Filing("f1", "ghost", "licence", FILED))
        with self.assertRaises(ms.MatterIntegrityError):
            spine.attach_exposure(ms.Exposure("e1", "ghost", 1.0, True))

    def test_an_unknown_view_is_refused(self):
        with self.assertRaises(ms.UnknownView):
            spine_with_matter().view("dashboard", "m1")

    def test_opening_the_same_matter_twice_is_idempotent(self):
        spine = spine_with_matter()
        first = spine.get("m1")
        spine.open_matter("m1", title="ignored")
        self.assertIs(spine.get("m1"), first)

    def test_a_matter_needs_an_id(self):
        with self.assertRaises(ValueError):
            ms.MatterSpine().open_matter("")


class TestExposureToHedgeFlywheel(unittest.TestCase):
    def exposures(self):
        return [ms.Exposure("e1", "m1", 600.0, True),
                ms.Exposure("e2", "m1", 400.0, False)]

    def test_share_is_the_hedgeable_fraction_of_quantified_loss(self):
        result = ms.hedgeable_share(self.exposures())
        self.assertEqual(result["total_expected_loss_usd"], 1000.0)
        self.assertEqual(result["hedgeable_usd"], 600.0)
        self.assertEqual(result["unhedgeable_usd"], 400.0)
        self.assertAlmostEqual(result["share"], 0.6)

    def test_no_quantified_exposure_reports_none_not_zero_or_one(self):
        """Either number would read as a finding when nothing was measured."""
        result = ms.hedgeable_share([])
        self.assertIsNone(result["share"])
        self.assertEqual(result["status"], "no quantified exposure")

    def test_a_negative_expected_loss_is_refused(self):
        with self.assertRaises(ValueError):
            ms.Exposure("e", "m1", -1.0, True)

    def test_a_single_point_is_explicitly_not_a_trend(self):
        result = ms.flywheel_trend([("q1", self.exposures())])
        self.assertIsNone(result["trend"])
        self.assertIn("insufficient", result["status"])

    def test_an_improving_trend_is_reported_with_direction(self):
        worse = [ms.Exposure("a", "m1", 900.0, False), ms.Exposure("b", "m1", 100.0, True)]
        better = [ms.Exposure("a", "m1", 100.0, False), ms.Exposure("b", "m1", 900.0, True)]
        result = ms.flywheel_trend([("q1", worse), ("q2", better)])
        self.assertGreater(result["trend"], 0)
        self.assertEqual(result["direction"], "improving")

    def test_a_declining_trend_is_not_dressed_up(self):
        better = [ms.Exposure("b", "m1", 900.0, True)]
        worse = [ms.Exposure("a", "m1", 900.0, False), ms.Exposure("b", "m1", 100.0, True)]
        self.assertEqual(ms.flywheel_trend([("q1", better), ("q2", worse)])["direction"],
                         "declining")

    def test_unhedgeable_exposure_feeds_the_foundry_largest_first(self):
        exposures = [ms.Exposure("small", "m1", 100.0, False),
                     ms.Exposure("big", "m1", 900.0, False),
                     ms.Exposure("covered", "m1", 500.0, True)]
        feed = ms.foundry_feed(exposures)
        self.assertEqual([g["exposure_id"] for g in feed], ["big", "small"])

    def test_zero_value_gaps_are_not_demand_signal(self):
        self.assertEqual(ms.foundry_feed([ms.Exposure("z", "m1", 0.0, False)]), [])


class TestRenewalAnnuity(unittest.TestCase):
    def test_a_filing_schedules_its_own_renewal(self):
        filing = ms.Filing("f1", "m1", "licence", FILED, "annual")
        self.assertEqual(filing.renewal_due(), date(2027, 1, 15))

    def test_each_cadence_resolves(self):
        for cadence, expected_days in ms.CADENCE_DAYS.items():
            filing = ms.Filing("f", "m1", "k", FILED, cadence)
            self.assertEqual((filing.renewal_due() - FILED).days, expected_days)

    def test_a_one_off_filing_has_no_renewal(self):
        """Inventing a renewal for a one-off would be noise, not an annuity."""
        self.assertIsNone(ms.Filing("f1", "m1", "notice", FILED).renewal_due())

    def test_an_unknown_cadence_is_refused(self):
        with self.assertRaises(ValueError):
            ms.Filing("f", "m1", "k", FILED, "fortnightly").renewal_due()

    def test_the_calendar_is_sorted_by_due_date(self):
        filings = [ms.Filing("late", "m1", "k", FILED, "biennial"),
                   ms.Filing("soon", "m1", "k", FILED, "quarterly")]
        self.assertEqual([r["filing_id"] for r in ms.renewal_calendar(filings)],
                         ["soon", "late"])

    def test_one_offs_are_absent_from_the_calendar(self):
        filings = [ms.Filing("once", "m1", "k", FILED),
                   ms.Filing("annual", "m1", "k", FILED, "annual")]
        self.assertEqual([r["filing_id"] for r in ms.renewal_calendar(filings)],
                         ["annual"])

    def test_due_within_surfaces_only_the_horizon(self):
        filings = [ms.Filing("q", "m1", "k", FILED, "quarterly"),
                   ms.Filing("a", "m1", "k", FILED, "annual")]
        soon = ms.due_within(filings, as_of=date(2026, 4, 1), days=30)
        self.assertEqual([r["filing_id"] for r in soon], ["q"])

    def test_overdue_is_reported_separately_from_upcoming(self):
        filings = [ms.Filing("q", "m1", "k", FILED, "quarterly")]
        self.assertEqual([r["filing_id"] for r in ms.overdue(filings, date(2027, 1, 1))],
                         ["q"])
        self.assertEqual(ms.overdue(filings, date(2026, 2, 1)), [])

    def test_a_negative_horizon_is_refused(self):
        with self.assertRaises(ValueError):
            ms.due_within([], as_of=FILED, days=-1)


class TestSideEffectFree(unittest.TestCase):
    def test_module_files_sends_and_hedges_nothing(self):
        for forbidden in ("file_filing", "send", "hedge", "submit", "notify"):
            self.assertFalse(hasattr(ms, forbidden), f"must not expose {forbidden}()")


if __name__ == "__main__":
    unittest.main()
