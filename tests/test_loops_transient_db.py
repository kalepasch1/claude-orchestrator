#!/usr/bin/env python3
"""loops.main() must survive a Supabase outage without a traceback.

A DNS/Supabase outage accounted for 1331 tracebacks in .runtime/logs/loops.err
(79% of that job's total) because the scheduled entry point ran run_due()
unguarded. These pin both directions: retryable outage is absorbed WITH a
diagnostic, and a real bug still raises.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import db  # noqa: E402
import loops  # noqa: E402


class LoopsEntryPointTests(unittest.TestCase):
    def test_a_supabase_outage_is_absorbed_and_reported(self):
        """The exact failure: the first db.select in ensure_all() cannot resolve."""
        boom = db.TransientDBError(
            "all Supabase endpoints unreachable for GET /rest/v1/projects: "
            "<urlopen error [Errno 8] nodename nor servname provided, or not known>"
        )
        buf = io.StringIO()
        with mock.patch.object(loops, "run_due", side_effect=boom):
            with redirect_stdout(buf):
                result = loops.main()

        self.assertEqual(result, 0)
        out = buf.getvalue()
        # Swallowed, but NOT silently — a silent except is the defect.
        self.assertIn("loops: skipped this cycle", out)
        self.assertIn("Supabase unreachable", out)
        # One diagnostic line, not a stack.
        self.assertEqual(len([ln for ln in out.splitlines() if ln.strip()]), 1)

    def test_a_real_bug_still_fails_loudly(self):
        """The catch is narrow on purpose: only the retryable class is absorbed."""
        with mock.patch.object(loops, "run_due", side_effect=TypeError("genuine defect")):
            with self.assertRaises(TypeError):
                loops.main()

    def test_the_happy_path_returns_the_fired_count(self):
        with mock.patch.object(loops, "run_due", return_value=7):
            self.assertEqual(loops.main(), 7)


if __name__ == "__main__":
    unittest.main()
