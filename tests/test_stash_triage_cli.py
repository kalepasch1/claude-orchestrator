#!/usr/bin/env python3
"""The recorded-baseline layer has to be REACHABLE, not merely correct.

Every function in the baseline layer was covered by tests and none of them could be
called: `main()` never referenced them and no other module imported them. A green
suite over unreachable code proves the code works, not that it runs — so these tests
pin the wiring itself, which is the part that was missing.

`triage()` is stubbed because it shells out to git: the subject here is which branch
`main()` takes and what it prints, not git's behaviour.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import stash_triage as st  # noqa: E402


FAKE_REPORT = {
    "repo": ".",
    "total": st.BASELINE["total"],  # an UNCHANGED pile
    "counts": {st.EMPTY: 1, st.ALREADY_LANDED: 1, st.RECOVERABLE: 1,
               st.CONFLICTED: 1, st.ERROR: 0},
    "runner_conflicted": 1,
    "recoverable_shas": [],
    "conflicted": [],
}


class CliWiringTests(unittest.TestCase):
    def setUp(self):
        self._real_triage = st.triage
        st.triage = lambda repo, limit=None: dict(FAKE_REPORT)
        self.addCleanup(lambda: setattr(st, "triage", self._real_triage))

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = st.main(argv)
        return rc, buf.getvalue()

    def test_baseline_flag_reaches_the_recorded_layer(self):
        """--baseline must actually render the recorded layer, not the live report."""
        rc, out = self._run(["--baseline"])
        self.assertEqual(rc, 0)
        self.assertIn("STASH TRIAGE — recorded", out)
        self.assertIn(st.summary_line(), out)

    def test_unchanged_pile_tells_the_operator_not_to_recompute(self):
        """The whole point of the layer: an unchanged pile is a recorded answer."""
        _, out = self._run(["--baseline"])
        self.assertIn("do NOT recompute", out)

    def test_baseline_flag_surfaces_the_unaccounted_gap(self):
        _, out = self._run(["--baseline"])
        self.assertIn("UNACCOUNTED", out)
        self.assertIn(str(st.unaccounted()), out)

    def test_baseline_json_carries_both_report_and_comparison(self):
        rc, out = self._run(["--baseline", "--json"])
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertIn("report", payload)
        self.assertIn("baseline_comparison", payload)
        self.assertFalse(payload["baseline_comparison"]["changed"])
        self.assertEqual(payload["baseline_comparison"]["delta"], 0)

    def test_a_grown_pile_scopes_the_work_to_the_new_stashes_only(self):
        grown = dict(FAKE_REPORT, total=st.BASELINE["total"] + 3)
        st.triage = lambda repo, limit=None: dict(grown)
        _, out = self._run(["--baseline"])
        self.assertIn("3 new stash(es)", out)
        self.assertIn("ONLY the new ones", out)

    def test_default_output_is_unchanged_by_the_new_flag(self):
        """Acceptance bar: preserve existing behaviour. Default must not gain baseline text."""
        _, out = self._run([])
        self.assertIn("stash triage — .", out)
        self.assertNotIn("STASH TRIAGE — recorded", out)

    def test_default_json_output_is_unchanged_by_the_new_flag(self):
        _, out = self._run(["--json"])
        payload = json.loads(out)
        self.assertNotIn("baseline_comparison", payload)
        self.assertEqual(payload["total"], FAKE_REPORT["total"])


if __name__ == "__main__":
    unittest.main()
