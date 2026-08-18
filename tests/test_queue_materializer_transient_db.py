#!/usr/bin/env python3
"""queue_materializer.main() must survive a Supabase outage without a traceback.

The job logged 367 tracebacks to .runtime/logs/queue-materializer.err with zero
successful runs recorded, so the fleet read it as 100% dead. Cause: run() opens
with _decomposed_parents(), whose db.select calls are unguarded, and the __main__
entry point called run() bare.

These pin both directions: a retryable outage is absorbed WITH a diagnostic, and a
real bug still raises.
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
import queue_materializer as qm  # noqa: E402


class MaterializerEntryPointTests(unittest.TestCase):
    def test_a_supabase_outage_is_absorbed_and_reported(self):
        """The recorded failure: a retryable PostgREST error during the parent scan."""
        boom = db.TransientDBError("HTTP Error 400: Bad Request for GET /rest/v1/tasks")
        buf = io.StringIO()
        with mock.patch.object(qm, "run", side_effect=boom):
            with redirect_stdout(buf):
                result = qm.main()

        self.assertEqual(result, 0)
        out = buf.getvalue()
        # Swallowed, but NOT silently — a silent except is the defect.
        self.assertIn("materializer: skipped this cycle", out)
        self.assertIn("Supabase unreachable", out)
        # One diagnostic line, not a stack.
        self.assertEqual(len([ln for ln in out.splitlines() if ln.strip()]), 1)

    def test_a_real_bug_still_fails_loudly(self):
        """The catch is narrow on purpose: only the retryable class is absorbed."""
        with mock.patch.object(qm, "run", side_effect=KeyError("genuine defect")):
            with self.assertRaises(KeyError):
                qm.main()

    def test_the_batch_slug_is_passed_through(self):
        with mock.patch.object(qm, "run", return_value=3) as runner:
            self.assertEqual(qm.main("batch-42"), 3)
            runner.assert_called_once_with("batch-42")


if __name__ == "__main__":
    unittest.main()
