#!/usr/bin/env python3
"""quality_gate — the gate that could not fail.

Two independent ways a mutation run used to pass no matter what it found:

  * the score was read with `re.search(r"(\\d+(\\.\\d+)?)\\s*%", stdout)` — the FIRST
    percentage anywhere in the output. Mutation runners stream progress and coverage
    percentages long before the summary line, so the number compared against the floor was
    usually not the mutation score at all.
  * an unparseable score was a pass. `score is not None and score < floor` means a run whose
    output format changed, or that printed no percentage, recorded "mutation None%" and
    returned pass=True.

Both are silent. A gate whose only failure mode is "the command exited non-zero" is a
subprocess call with extra steps.
"""
import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import quality_gate  # noqa: E402


def _completed(stdout="", returncode=0):
    return subprocess.CompletedProcess(args="mut", returncode=returncode, stdout=stdout,
                                       stderr="")


STRYKER_OUTPUT = """
Starting mutation testing
Mutation testing 12% (5/40)
Mutation testing 55% (22/40)
Ran 1.20 tests per mutant on average.
File coverage: 91.30%
Mutation score: 41.50%
"""


class MutationScoreParsingTest(unittest.TestCase):
    def test_the_labelled_score_wins_over_earlier_percentages(self):
        # The regression: progress ("12%") and coverage ("91.30%") both come first.
        self.assertEqual(quality_gate._mutation_score(STRYKER_OUTPUT), 41.50)

    def test_the_alternate_phrasing_is_read(self):
        out = "78.25% mutation score based on covered code\n"
        self.assertEqual(quality_gate._mutation_score(out), 78.25)

    def test_a_bare_percentage_is_a_last_resort_and_takes_the_last_one(self):
        self.assertEqual(quality_gate._mutation_score("step 10%\nfinal 66%\n"), 66.0)

    def test_no_percentage_at_all_is_unreadable_not_zero(self):
        # None and 0.0 must not be conflated: 0.0 is a real, terrible score that should fail
        # a floor of 60; None means we do not know, which is a different verdict.
        self.assertIsNone(quality_gate._mutation_score("no numbers here"))
        self.assertIsNone(quality_gate._mutation_score(""))
        self.assertEqual(quality_gate._mutation_score("Mutation score: 0.00%"), 0.0)

    def test_integers_and_decimals_both_parse(self):
        self.assertEqual(quality_gate._mutation_score("Mutation score: 80%"), 80.0)
        self.assertEqual(quality_gate._mutation_score("Mutation score: 80.5 %"), 80.5)


class MutationGateVerdictTest(unittest.TestCase):
    def _run(self, stdout, returncode=0, floor=None):
        env = {"MUTATION_CMD": "npx stryker run"}
        if floor is not None:
            env["MUTATION_MIN_SCORE"] = str(floor)
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(quality_gate, "_run_cmd",
                               return_value=_completed(stdout, returncode)), \
             mock.patch.object(quality_gate, "_validate_repo_path", side_effect=lambda p: p):
            return quality_gate.run(".")

    def test_a_score_under_the_floor_fails(self):
        out = self._run(STRYKER_OUTPUT, floor=60)
        self.assertFalse(out["pass"])
        self.assertIn("41.5", out["notes"])

    def test_a_score_over_the_floor_passes(self):
        self.assertTrue(self._run("Mutation score: 82.00%", floor=60)["pass"])

    def test_the_floor_boundary_is_inclusive(self):
        self.assertTrue(self._run("Mutation score: 60.00%", floor=60)["pass"])

    def test_an_unreadable_score_fails_when_a_floor_is_configured(self):
        # THE REGRESSION. Previously: pass=True, notes="mutation None%".
        out = self._run("stryker crashed, no summary written", floor=60)
        self.assertFalse(out["pass"], "an unverifiable floor must not report success")
        self.assertIn("unreadable", out["notes"])

    def test_an_unreadable_score_passes_when_no_floor_is_configured(self):
        # Nothing to enforce — but the notes must still say the score was not read.
        out = self._run("no summary")
        self.assertTrue(out["pass"])
        self.assertIn("unreadable", out["notes"])

    def test_a_nonzero_exit_fails_and_says_so(self):
        out = self._run("Mutation score: 99.00%", returncode=3, floor=60)
        self.assertFalse(out["pass"])
        self.assertIn("exit 3", out["notes"])

    def test_progress_percentages_alone_cannot_satisfy_the_floor(self):
        # "Mutation testing 95% (38/40)" is progress, not a score. Under the old first-match
        # parse this passed a floor of 90 on a run whose real score was 41.5%.
        out = self._run(STRYKER_OUTPUT, floor=90)
        self.assertFalse(out["pass"])


class UnconfiguredGateTest(unittest.TestCase):
    def test_nothing_configured_is_a_pass_that_admits_it(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(quality_gate, "_validate_repo_path", side_effect=lambda p: p):
            out = quality_gate.run(".")
        self.assertTrue(out["pass"])
        self.assertIn("no extra quality gates configured", out["notes"])

    def test_property_command_failure_still_fails(self):
        with mock.patch.dict(os.environ, {"PROPERTY_CMD": "npm run test:property"}, clear=True), \
             mock.patch.object(quality_gate, "_run_cmd", return_value=_completed("", 1)), \
             mock.patch.object(quality_gate, "_validate_repo_path", side_effect=lambda p: p):
            out = quality_gate.run(".")
        self.assertFalse(out["pass"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
