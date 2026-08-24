"""The on-fire check must be right in the two directions that cost differently.

A false OK hides a real fire; a false alarm on a healthy fleet trains the
operator to ignore the check, which is the same outcome one run later. So the
cases pinned here are mostly the ones that could go either way: a KPI that
IMPROVED threefold, a baseline of zero, a missing row, and a row whose own
`ratios_vs_baseline` disagrees with its raw numbers.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import meta_monitor_kpi_check as kpi  # noqa: E402


def _row(measured, baseline, **extra):
    value = {"baseline_used": baseline, "measured_at": "2026-08-24T10:00:00Z"}
    value.update(measured)
    value.update(extra)
    return {"key": kpi.BASELINE_KEY, "value": value}


class Ratios(unittest.TestCase):
    def test_a_ratio_is_measured_over_baseline(self):
        self.assertAlmostEqual(
            kpi.compute_ratios({"queued_4d": 1139}, {"queued_4d": 1375})["queued_4d"],
            0.8284,
            places=4,
        )

    def test_a_zero_baseline_is_skipped_not_infinite(self):
        """A brand-new KPI starts at 0. inf would fire the alarm on its first
        measurement, every time, for a metric nobody has a baseline for yet."""
        self.assertEqual(kpi.compute_ratios({"alerts": 5}, {"alerts": 0}), {})

    def test_missing_and_non_numeric_values_are_skipped(self):
        ratios = kpi.compute_ratios(
            {"queued": 10, "phantom": "n/a", "alerts": None, "quar_24h": 4},
            {"queued": 5, "phantom": 1, "alerts": 1},
        )
        self.assertEqual(set(ratios), {"queued"})

    def test_a_boolean_is_not_treated_as_a_number(self):
        """True == 1 in Python. Silently scoring a flag as a KPI is worse than
        skipping it, because the number looks plausible."""
        self.assertEqual(kpi.compute_ratios({"queued": True}, {"queued": 1}), {})


class OnFire(unittest.TestCase):
    def test_at_the_threshold_counts_as_on_fire(self):
        self.assertEqual(
            [h["kpi"] for h in kpi.on_fire({"queued_4d": 2.0}, 2.0)], ["queued_4d"]
        )

    def test_just_below_the_threshold_does_not(self):
        self.assertEqual(kpi.on_fire({"queued_4d": 1.9999}, 2.0), [])

    def test_a_higher_is_better_kpi_is_never_on_fire(self):
        """Tripling merged_24h is three times the throughput, not an emergency."""
        self.assertEqual(kpi.on_fire({"merged_24h": 3.0}, 2.0), [])

    def test_an_unknown_kpi_is_not_on_fire(self):
        """A KPI added upstream without a direction must not alarm by default."""
        self.assertEqual(kpi.on_fire({"some_new_metric": 9.0}, 2.0), [])

    def test_the_worst_offender_is_reported_first(self):
        hot = kpi.on_fire({"queued_4d": 2.5, "alerts": 9.0, "quar_24h": 3.0}, 2.0)
        self.assertEqual([h["kpi"] for h in hot], ["alerts", "quar_24h", "queued_4d"])


class Evaluate(unittest.TestCase):
    def test_the_live_shape_reads_healthy(self):
        """The real 2026-08-24 row: queued_4d 1208 vs baseline 1375."""
        verdict = kpi.evaluate(
            _row(
                {"queued_4d": 1208, "queued": 1345, "p90_h": 987.2, "merged_24h": 32},
                {"queued_4d": 1375, "queued": 1529, "p90_h": 1092.9, "merged_24h": 32},
            )
        )
        self.assertTrue(verdict["determinable"])
        self.assertTrue(verdict["ok"])
        self.assertEqual(verdict["on_fire"], [])
        self.assertAlmostEqual(verdict["ratios"]["queued_4d"], 0.8785, places=4)

    def test_a_doubled_queued_4d_is_caught(self):
        verdict = kpi.evaluate(_row({"queued_4d": 2750}, {"queued_4d": 1375}))
        self.assertFalse(verdict["ok"])
        self.assertEqual([h["kpi"] for h in verdict["on_fire"]], ["queued_4d"])

    def test_ratios_are_recomputed_not_trusted(self):
        """A check that reads the number it is verifying verifies nothing."""
        verdict = kpi.evaluate(
            _row(
                {"queued_4d": 2750},
                {"queued_4d": 1375},
                ratios_vs_baseline={"queued_4d": 1.0},  # the row claims healthy
            )
        )
        self.assertFalse(verdict["ok"], "believed the row's own arithmetic")
        self.assertAlmostEqual(verdict["ratios"]["queued_4d"], 2.0)

    def test_a_json_string_value_is_parsed(self):
        import json

        row = _row({"queued_4d": 1208}, {"queued_4d": 1375})
        self.assertTrue(kpi.evaluate({"key": row["key"], "value": json.dumps(row["value"])})["ok"])

    # -- undeterminable is not healthy -------------------------------------

    def test_a_missing_row_is_undeterminable_not_ok(self):
        verdict = kpi.evaluate(None)
        self.assertFalse(verdict["determinable"])
        self.assertFalse(verdict["ok"], "'could not read' must never report OK")

    def test_unparseable_json_is_undeterminable(self):
        self.assertFalse(kpi.evaluate({"value": "{not json"})["determinable"])

    def test_a_row_with_no_baseline_is_undeterminable(self):
        verdict = kpi.evaluate({"value": {"queued_4d": 1208}})
        self.assertFalse(verdict["determinable"])
        self.assertIn("baseline", verdict["reason"])


class Loading(unittest.TestCase):
    def test_a_failing_fetch_returns_none_rather_than_raising(self):
        def boom(_key):
            raise RuntimeError("control plane down")

        self.assertIsNone(kpi.load_baseline_row(fetch=boom))

    def test_an_injected_fetch_is_used(self):
        seen = {}

        def fetch(key):
            seen["key"] = key
            return {"value": {"queued_4d": 1, "baseline_used": {"queued_4d": 1}}}

        self.assertIsNotNone(kpi.load_baseline_row(fetch=fetch))
        self.assertEqual(seen["key"], kpi.BASELINE_KEY)


class ExitStatus(unittest.TestCase):
    """0 healthy / 1 on fire / 2 could-not-tell must stay distinguishable —
    a caller that cannot separate 1 from 2 will treat an outage as an all-clear."""

    def _main_with(self, row):
        original = kpi.load_baseline_row
        kpi.load_baseline_row = lambda fetch=None: row
        try:
            return kpi.main(["--json"])
        finally:
            kpi.load_baseline_row = original

    def test_healthy_exits_zero(self):
        self.assertEqual(
            self._main_with(_row({"queued_4d": 1208}, {"queued_4d": 1375})), 0
        )

    def test_on_fire_exits_one(self):
        self.assertEqual(
            self._main_with(_row({"queued_4d": 2750}, {"queued_4d": 1375})), 1
        )

    def test_undeterminable_exits_two(self):
        self.assertEqual(self._main_with(None), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
