"""Fail-soft tests for cost_ledger.

The recovered `improve/cost-ledger-fail-soft` work landed with no test, which is
exactly why it sat unmerged and unnoticed on a local-only branch for days. These
assert the behaviour the branch claims: cost accounting is pure bookkeeping and
must never wedge a run, but it must also never swallow a failure silently.
"""

import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cost_ledger  # noqa: E402


class ParseNumber(unittest.TestCase):
    def test_parses_comma_grouped_digits(self):
        self.assertEqual(cost_ledger._n("1,234"), 1234)

    def test_bad_input_returns_zero_instead_of_raising(self):
        for bad in ("", "abc", None, "12.5.6", []):
            self.assertEqual(cost_ledger._n(bad), 0, repr(bad))


class LedgerPath(unittest.TestCase):
    """record()/report() write to a module-level LEDGER path; swap it per test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig = cost_ledger.LEDGER
        cost_ledger.LEDGER = os.path.join(self.tmp.name, "sub", "cost.jsonl")
        self.addCleanup(lambda: setattr(cost_ledger, "LEDGER", self._orig))

    def capture_stderr(self):
        buf = io.StringIO()
        orig = sys.stderr
        sys.stderr = buf
        self.addCleanup(lambda: setattr(sys, "stderr", orig))
        return buf


class Record(LedgerPath):
    def test_missing_log_still_returns_a_row_and_writes_it(self):
        row = cost_ledger.record("beethoven", "slug", "claude-opus-5",
                                 os.path.join(self.tmp.name, "no-such.log"))
        self.assertEqual(row["input_tokens"], 0)
        self.assertEqual(row["output_tokens"], 0)
        with open(cost_ledger.LEDGER) as fh:
            self.assertEqual(json.loads(fh.read().strip())["slug"], "slug")

    def test_unwritable_ledger_does_not_raise_but_does_complain(self):
        # The whole point of the fail-soft convention: a broken ledger path must
        # not wedge the run, and must not vanish quietly either.
        cost_ledger.LEDGER = os.path.join(self.tmp.name, "cost.jsonl", "x.jsonl")
        open(os.path.join(self.tmp.name, "cost.jsonl"), "w").close()
        err = self.capture_stderr()
        row = cost_ledger.record("p", "s", "m", "nope.log")
        self.assertEqual(row["slug"], "s")
        self.assertIn("cost_ledger", err.getvalue())


class Report(LedgerPath):
    def test_no_ledger_is_reported_not_raised(self):
        cost_ledger.report()  # must not raise

    def test_malformed_lines_are_skipped_and_good_rows_still_total(self):
        os.makedirs(os.path.dirname(cost_ledger.LEDGER), exist_ok=True)
        with open(cost_ledger.LEDGER, "w") as fh:
            fh.write(json.dumps({"project": "a", "model": "m", "usd": 1.5}) + "\n")
            fh.write("{ this is not json\n")
            fh.write("\n")
            fh.write(json.dumps({"usd": "0.5"}) + "\n")  # missing keys, str cost
        buf = io.StringIO()
        orig = sys.stdout
        sys.stdout = buf
        try:
            cost_ledger.report()
        finally:
            sys.stdout = orig
        out = buf.getvalue()
        self.assertIn("TOTAL $2.00", out)
        self.assertIn("unknown", out)


if __name__ == "__main__":
    unittest.main()
