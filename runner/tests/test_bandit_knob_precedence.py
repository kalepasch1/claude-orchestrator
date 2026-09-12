"""The bandit tuning knobs must be fleet-pushable without breaking local overrides.

CLAUDE.md requires ORCH_-prefixed config keys: `fleet_control.py` pushes a value to
every machine only if the key matches its `_SAFE_PREFIXES` allowlist, which starts
with "ORCH_". A bare `BANDIT_ACCEPT_CONFIDENCE` cannot be pushed at all.

The knobs recovered from commit 12001806 use the bare names, and so does the test
suite recovered alongside them. Renaming outright would have made the knobs pushable
and silently ignored every operator's existing local `BANDIT_*` value — the runner
would read as configured and behave as though it were not, which is the same class of
failure as the missing constant this recovery exists to fix.

So `_knob` reads both, ORCH_ first. Nothing in the recovered suite covers that
precedence, because on that branch it did not exist. These cases do.
"""
import importlib
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bandit  # noqa: E402


class KnobPrecedence(unittest.TestCase):
    NAMES = (
        "ORCH_BANDIT_ACCEPT_CONFIDENCE", "BANDIT_ACCEPT_CONFIDENCE",
        "ORCH_BANDIT_ACCEPT_MIN_SAMPLES", "BANDIT_ACCEPT_MIN_SAMPLES",
        "ORCH_BANDIT_ACCEPTANCE", "BANDIT_ACCEPTANCE",
    )

    def setUp(self):
        self._saved = {n: os.environ.get(n) for n in self.NAMES}
        for n in self.NAMES:
            os.environ.pop(n, None)

    def tearDown(self):
        for n, v in self._saved.items():
            if v is None:
                os.environ.pop(n, None)
            else:
                os.environ[n] = v
        importlib.reload(bandit)

    def _reload(self):
        return importlib.reload(bandit)

    def test_defaults_are_the_recovered_values_not_reinvented_ones(self):
        # These are commit 12001806's values verbatim. If a future edit "tidies" them,
        # the bandit starts routing model selection on a different threshold than the
        # one the recovered 46-case suite was written against.
        m = self._reload()
        self.assertAlmostEqual(m.ACCEPTANCE_CONFIDENCE, 0.95)
        self.assertEqual(m.ACCEPTANCE_MIN_SAMPLES, 12)
        self.assertTrue(m.ACCEPTANCE_ENABLED)

    def test_orch_prefixed_name_is_read(self):
        os.environ["ORCH_BANDIT_ACCEPT_CONFIDENCE"] = "0.99"
        self.assertAlmostEqual(self._reload().ACCEPTANCE_CONFIDENCE, 0.99)

    def test_bare_name_is_still_honoured(self):
        os.environ["BANDIT_ACCEPT_CONFIDENCE"] = "0.80"
        self.assertAlmostEqual(self._reload().ACCEPTANCE_CONFIDENCE, 0.80)

    def test_orch_wins_when_both_are_set(self):
        os.environ["ORCH_BANDIT_ACCEPT_CONFIDENCE"] = "0.99"
        os.environ["BANDIT_ACCEPT_CONFIDENCE"] = "0.80"
        self.assertAlmostEqual(self._reload().ACCEPTANCE_CONFIDENCE, 0.99)

    def test_precedence_holds_for_every_knob_not_just_confidence(self):
        os.environ["ORCH_BANDIT_ACCEPT_MIN_SAMPLES"] = "40"
        os.environ["BANDIT_ACCEPT_MIN_SAMPLES"] = "3"
        os.environ["ORCH_BANDIT_ACCEPTANCE"] = "false"
        os.environ["BANDIT_ACCEPTANCE"] = "true"
        m = self._reload()
        self.assertEqual(m.ACCEPTANCE_MIN_SAMPLES, 40)
        self.assertFalse(m.ACCEPTANCE_ENABLED)

    def test_kill_switch_accepts_the_documented_spellings(self):
        for value, expected in (("false", False), ("0", False), ("no", False), ("off", False),
                                ("true", True), ("1", True), ("yes", True), ("on", True),
                                ("TRUE", True), ("Off", False)):
            os.environ["ORCH_BANDIT_ACCEPTANCE"] = value
            self.assertEqual(self._reload().ACCEPTANCE_ENABLED, expected, f"for {value!r}")

    def test_knob_helper_is_pure_lookup_with_no_side_effects(self):
        m = self._reload()
        os.environ.pop("ORCH_BANDIT_NOT_A_REAL_KNOB", None)
        os.environ.pop("BANDIT_NOT_A_REAL_KNOB", None)
        self.assertEqual(m._knob("BANDIT_NOT_A_REAL_KNOB", "fallback"), "fallback")
        self.assertNotIn("ORCH_BANDIT_NOT_A_REAL_KNOB", os.environ)
        self.assertNotIn("BANDIT_NOT_A_REAL_KNOB", os.environ)


class ConstantsAreDefined(unittest.TestCase):
    """The regression this whole task exists for.

    The auto-resolved merge at 12001806 kept `self.confidence = ACCEPTANCE_CONFIDENCE`
    and dropped the line defining it, so importing the module raised
    `NameError: name 'ACCEPTANCE_CONFIDENCE' is not defined` and 51 bandit tests failed
    at collection. A name that is read but never defined is invisible to every check
    that does not actually import the module.
    """

    def test_every_name_the_tracker_reads_is_defined(self):
        for name in ("ACCEPTANCE_CONFIDENCE", "ACCEPTANCE_MIN_SAMPLES",
                     "ACCEPTANCE_ENABLED", "_Z", "_z_for",
                     "PerformanceTracker", "tracker_from_outcomes"):
            self.assertTrue(hasattr(bandit, name), f"bandit.{name} is missing")

    def test_constructing_the_tracker_does_not_raise(self):
        # The exact call that failed: PerformanceTracker() reads ACCEPTANCE_CONFIDENCE
        # in __init__, so a missing constant is a NameError at construction, not import.
        self.assertAlmostEqual(bandit.PerformanceTracker().confidence,
                               bandit.ACCEPTANCE_CONFIDENCE)

    def test_z_table_covers_the_default_confidence(self):
        # _z_for(ACCEPTANCE_CONFIDENCE) must resolve, or the gate is undefined at its
        # own default and only fails once enough samples accumulate to reach it.
        self.assertIsNotNone(bandit._z_for(bandit.ACCEPTANCE_CONFIDENCE))


if __name__ == "__main__":
    unittest.main()
