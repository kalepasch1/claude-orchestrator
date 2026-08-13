#!/usr/bin/env python3
"""The closure verdict has to be ASKABLE, not merely computable.

release_closure.py was fully tested and completely unreachable: nothing in the tree
imported it and it had no entry point, so `evaluate_closure` could never actually be
called. These tests pin the entry point — the part that was missing — rather than the
evaluation logic, which tests/test_release_closure.py already covers.
"""
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr

RUNNER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runner")
sys.path.insert(0, RUNNER)

import release_closure as rc  # noqa: E402


def run(argv, stdin_text=None):
    out, err = io.StringIO(), io.StringIO()
    real_stdin = sys.stdin
    if stdin_text is not None:
        sys.stdin = io.StringIO(stdin_text)
    try:
        with redirect_stdout(out), redirect_stderr(err):
            code = rc.main(argv)
    finally:
        sys.stdin = real_stdin
    return code, out.getvalue(), err.getvalue()


MERGED_ONLY = {"slug": "demo", "branch": "agent/demo", "merge_commit": "abc123"}


class ClosureCliTests(unittest.TestCase):
    def test_merged_only_is_not_done_and_exits_nonzero(self):
        """The module's entire thesis, now reachable from a shell."""
        code, out, _ = run(["-"], json.dumps(MERGED_ONLY))
        self.assertEqual(code, 1)
        self.assertIn("MERGED is not DONE", out)
        self.assertIn("closed: False", out)

    def test_it_names_what_is_missing(self):
        _, out, _ = run(["-"], json.dumps(MERGED_ONLY))
        self.assertIn("missing:", out)
        self.assertIn("deployed_sha", out)

    def test_json_mode_carries_the_full_record(self):
        code, out, _ = run(["--json", "-"], json.dumps(MERGED_ONLY))
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertIn("closure", payload)
        self.assertFalse(payload["may_report_complete"])
        self.assertIn("reason", payload)

    def test_unreadable_evidence_exits_2_rather_than_crashing(self):
        code, _, err = run(["-"], "this is not json")
        self.assertEqual(code, 2)
        self.assertIn("unreadable evidence", err)

    def test_reads_evidence_from_a_file_path(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(MERGED_ONLY, fh)
            path = fh.name
        try:
            code, out, _ = run([path])
            self.assertEqual(code, 1)
            self.assertIn("stage:", out)
        finally:
            os.unlink(path)

    def test_missing_file_is_reported_not_raised(self):
        code, _, err = run(["/nonexistent/evidence.json"])
        self.assertEqual(code, 2)
        self.assertIn("unreadable evidence", err)


if __name__ == "__main__":
    unittest.main()
