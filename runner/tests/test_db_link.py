"""db_link: the memos --render path feeds render_markdown a LEDGER (evidence joined to
findings via db_memo._load_ledger), not raw legal_memo_evidence rows — raw rows carry no
status/fp/weight and crashed the renderer (KeyError: 'status')."""
import contextlib
import io
import os
import sys
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import db_link  # noqa: E402


def _args(project="apparently-law", render="records_integrity_and_audit_trail"):
    return types.SimpleNamespace(project=project, render=render)


class MemosRenderTest(unittest.TestCase):
    DRAFT = {"id": "m1", "project": "apparently-law",
             "memo_kind": "records_integrity_and_audit_trail", "body": "", "title": "t"}

    def test_render_uses_ledger_not_raw_evidence_rows(self):
        import db
        import db_memo
        ledger = [{"fp": "abc", "status": "open", "weight": 1.0, "direction": "undermines",
                   "argument_key": "contemporaneous_records", "severity": "medium",
                   "title": "No created_at", "object": "public.t", "first_seen": "2026-09-12",
                   "last_seen": "2026-09-12", "resolved_at": None, "metrics_excerpt": "{}",
                   "remediation": "add created_at default now()"}]
        calls = []
        out = io.StringIO()
        with patch.object(db, "select", lambda t, p: [dict(self.DRAFT)]), \
             patch.object(db_memo, "_load_ledger", lambda mid: calls.append(mid) or ledger), \
             contextlib.redirect_stdout(out):
            rc = db_link.cmd_memos(_args())
        self.assertEqual(rc, 0)
        self.assertEqual(calls, ["m1"], "the render path must come through _load_ledger")
        self.assertIn("contemporaneous_records", out.getvalue())

    def test_render_with_stored_body_prints_body_and_skips_ledger(self):
        import db
        import db_memo
        with patch.object(db, "select", lambda t, p: [dict(self.DRAFT, body="STORED BODY")]), \
             patch.object(db_memo, "_load_ledger",
                          side_effect=AssertionError("ledger must not load when a body exists")), \
             contextlib.redirect_stdout(out := io.StringIO()):
            rc = db_link.cmd_memos(_args())
        self.assertEqual(rc, 0)
        self.assertIn("STORED BODY", out.getvalue())

    def test_render_unknown_memo_is_a_clean_miss(self):
        import db
        with patch.object(db, "select", lambda t, p: []), \
             contextlib.redirect_stdout(out := io.StringIO()):
            rc = db_link.cmd_memos(_args(render="nope"))
        self.assertEqual(rc, 2)
        self.assertIn("no memo nope", out.getvalue())


if __name__ == "__main__":
    unittest.main()
