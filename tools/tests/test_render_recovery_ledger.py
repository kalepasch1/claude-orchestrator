#!/usr/bin/env python3
"""Tests for tools/render_recovery_ledger.py."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_recovery_ledger as RR  # noqa: E402


def item(cls="RECOVERABLE_VALUE", **kw):
    d = {"kind": "rescue_ref", "source": "refs/orch-rescue/x",
         "classification": cls, "reason": "absent from base",
         "paths": ["a.py"]}
    d.update(kw)
    return d


def ledger(items=None, **meta):
    m = {"project": "beethoven", "repo": "/repo", "base": "origin/master",
         "baseSha": "abcdef1234567890", "fingerprint": "fp123",
         "activeRefCount": 12, "generatedAt": "2026-08-24T00:00:00.000Z"}
    m.update(meta)
    return {"meta": m, "counts": {"STALE": 99},
            "items": items if items is not None else [item()]}


class TestHistogram(unittest.TestCase):
    def test_counts_items(self):
        h = RR.histogram([item(), item("ALREADY_PRESENT"), item()])
        self.assertEqual(h, {"RECOVERABLE_VALUE": 2, "ALREADY_PRESENT": 1})

    def test_unrecognised_label_is_unknown(self):
        self.assertEqual(RR.histogram([item("NONSENSE")]), {"UNKNOWN": 1})

    def test_missing_and_non_dict_are_unknown(self):
        self.assertEqual(RR.histogram([{"kind": "x"}, "junk", None]),
                         {"UNKNOWN": 3})

    def test_empty_inputs(self):
        self.assertEqual(RR.histogram([]), {})
        self.assertEqual(RR.histogram(None), {})


class TestCellEscaping(unittest.TestCase):
    def test_pipe_escaped(self):
        self.assertEqual(RR.cell("a|b"), "a\\|b")

    def test_newlines_flattened(self):
        self.assertEqual(RR.cell("a\nb\r\nc"), "a b  c")

    def test_none_is_empty(self):
        self.assertEqual(RR.cell(None), "")

    def test_list_joined(self):
        self.assertEqual(RR.cell(["a", "b"]), "a, b")

    def test_number_stringified(self):
        self.assertEqual(RR.cell(7), "7")


class TestPathsOf(unittest.TestCase):
    def test_prefers_paths_list(self):
        self.assertEqual(RR.paths_of({"paths": ["a", "b"], "path": "c"}), "a, b")

    def test_falls_back_to_path(self):
        self.assertEqual(RR.paths_of({"path": "c"}), "c")

    def test_empty_when_neither(self):
        self.assertEqual(RR.paths_of({}), "")

    def test_non_dict_safe(self):
        self.assertEqual(RR.paths_of("junk"), "")


class TestRender(unittest.TestCase):
    def test_header_reports_totals_and_zero_unknown(self):
        out = RR.render(ledger([item(), item("ALREADY_PRESENT")]))
        self.assertIn("Evidence items classified: **2** (UNKNOWN: **0**)", out)
        self.assertIn("Audit fingerprint: `fp123`", out)
        self.assertIn("origin/master", out)

    def test_counts_derived_from_items_not_stale_counts_block(self):
        out = RR.render(ledger([item(), item()]))
        self.assertIn("| RECOVERABLE_VALUE | 2 |", out)
        self.assertNotIn("STALE", out)

    def test_unknown_triggers_completion_warning(self):
        out = RR.render(ledger([item("WAT")]))
        self.assertIn("(UNKNOWN: **1**)", out)
        self.assertIn("Completion bar not met", out)

    def test_no_warning_when_clean(self):
        self.assertNotIn("Completion bar not met", RR.render(ledger()))

    def test_only_remaining_value_items_itemised(self):
        out = RR.render(ledger([
            item("RECOVERABLE_VALUE", source="KEEP"),
            item("ALREADY_PRESENT", source="DROP"),
            item("SUPERSEDED_BY_NEWER", source="DROPTOO"),
        ]))
        self.assertIn("KEEP", out)
        self.assertNotIn("DROP", out)

    def test_empty_remaining_states_none(self):
        out = RR.render(ledger([item("ALREADY_PRESENT")]))
        self.assertIn("None: every evidence item", out)

    def test_truncation_note_when_over_max_rows(self):
        out = RR.render(ledger([item() for _ in range(5)]), max_rows=2)
        self.assertIn("3 further item(s)", out)

    def test_no_truncation_note_when_under_limit(self):
        self.assertNotIn("further item(s)", RR.render(ledger(), max_rows=10))

    def test_restamp_provenance_surfaced(self):
        out = RR.render(ledger(restampedFrom="oldfp"))
        self.assertIn("re-stamp from fingerprint `oldfp`", out)
        self.assertIn("not an independent scan", out)

    def test_read_only_note_present(self):
        self.assertIn("No stash was popped", RR.render(ledger()))

    def test_custom_title_used(self):
        self.assertTrue(RR.render(ledger(), title="My Title").startswith("# My Title"))

    def test_missing_meta_tolerated(self):
        out = RR.render({"items": [item()]})
        self.assertIn("unknown-project", out)
        self.assertIn("`unknown`", out)

    def test_pipe_in_reason_does_not_break_row(self):
        out = RR.render(ledger([item(reason="a|b")]))
        row = [l for l in out.splitlines() if "refs/orch-rescue/x" in l][0]
        # The pipe is escaped, so it does not create a sixth column: 6 real
        # delimiters for 5 columns, plus the one escaped literal.
        self.assertIn("a\\|b", row)
        self.assertEqual(row.replace("\\|", "").count("|"), 6)

    def test_table_row_count_matches_remaining(self):
        out = RR.render(ledger([item(), item(), item("ALREADY_PRESENT")]))
        rows = [l for l in out.splitlines() if l.startswith("| `refs/")]
        self.assertEqual(len(rows), 2)


def flat_item(cls="RECOVERABLE_VALUE", **kw):
    """An item as `reconcile_all_evidence.py` emits it."""
    d = {"kind": "orchestrator_rescue_refs", "classification": cls,
         "ref": "refs/orch-rescue/20260803T000716-x",
         "evidence": "2 path(s) absent from origin/master",
         "disposition": "queue a focused recovery task",
         "files": ["runner/a.py", "runner/b.py"]}
    d.update(kw)
    return d


def flat_ledger(items=None):
    return {"audit_fingerprint": "fpflat", "base": "origin/master",
            "base_sha": "5c4eaf2f5620aa6e263de622869f217a437190f9",
            "evidence_kind": "combined_local_chatgpt_codex_evidence",
            "stages": {"reconcile_rescue_refs.py": "ok",
                       "reconcile_local_branches.py": "ok"},
            "counts": {"STALE": 1}, "total": 0, "unknown": 5,
            "items": items if items is not None else [flat_item()]}


class TestFlatShape(unittest.TestCase):
    def test_header_reads_flat_fields(self):
        out = RR.render(flat_ledger())
        self.assertIn("Audit fingerprint: `fpflat`", out)
        self.assertIn("origin/master", out)
        self.assertIn("5c4eaf2f5620", out)
        # The flat driver shape carries no repo/project field, so those two
        # legitimately render as unknown; the audit facts must not.
        self.assertNotIn("Audit fingerprint: `unknown`", out)
        self.assertNotIn("Compared against: `unknown`", out)

    def test_evidence_kind_and_stages_surfaced(self):
        out = RR.render(flat_ledger())
        self.assertIn("combined_local_chatgpt_codex_evidence", out)
        self.assertIn("reconcile_rescue_refs.py=ok", out)

    def test_flat_item_populates_table(self):
        out = RR.render(flat_ledger())
        row = [l for l in out.splitlines() if l.startswith("| `refs/")][0]
        self.assertIn("refs/orch-rescue/20260803T000716-x", row)
        self.assertIn("runner/a.py, runner/b.py", row)
        self.assertIn("absent from origin/master", row)

    def test_unknown_recomputed_not_taken_from_flat_field(self):
        # The source ledger claims unknown=5; the render must count the items.
        self.assertIn("(UNKNOWN: **0**)", RR.render(flat_ledger()))

    def test_source_of_precedence(self):
        self.assertEqual(RR.source_of({"source": "s", "ref": "r"}), "s")
        self.assertEqual(RR.source_of({"ref": "r"}), "r")
        self.assertEqual(RR.source_of({"branch": "b"}), "b")
        self.assertEqual(RR.source_of({}), "")
        self.assertEqual(RR.source_of("junk"), "")

    def test_reason_of_precedence(self):
        self.assertEqual(RR.reason_of({"reason": "a", "evidence": "b"}), "a")
        self.assertEqual(RR.reason_of({"evidence": "b"}), "b")
        self.assertEqual(RR.reason_of({"disposition": "c"}), "c")
        self.assertEqual(RR.reason_of({}), "")

    def test_paths_of_reads_files_key(self):
        self.assertEqual(RR.paths_of({"files": ["x", "y"]}), "x, y")

    def test_paths_prefers_paths_over_files(self):
        self.assertEqual(RR.paths_of({"paths": ["p"], "files": ["f"]}), "p")

    def test_header_fields_meta_shape_wins(self):
        hf = RR.header_fields(ledger())
        self.assertEqual(hf["fingerprint"], "fp123")

    def test_header_fields_non_dict_safe(self):
        self.assertEqual(RR.header_fields("junk"), {})


class TestLoadAndCli(unittest.TestCase):
    def test_load_missing_returns_empty(self):
        self.assertEqual(RR.load("/nonexistent/x.json"), {})

    def test_load_malformed_returns_empty(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            fh.write("{oops")
            p = fh.name
        try:
            self.assertEqual(RR.load(p), {})
        finally:
            os.unlink(p)

    def test_cli_happy_path(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l.json")
            with open(src, "w") as fh:
                json.dump(ledger(), fh)
            out = os.path.join(d, "sub", "l.md")
            self.assertEqual(RR.main(["--in", src, "--out", out]), 0)
            self.assertIn("Audit fingerprint", open(out).read())

    def test_cli_refuses_bad_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "l.json")
            with open(src, "w") as fh:
                json.dump({"meta": {}}, fh)
            rc = RR.main(["--in", src, "--out", os.path.join(d, "o.md")])
            self.assertEqual(rc, 2)

    def test_cli_refuses_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            rc = RR.main(["--in", os.path.join(d, "nope.json"),
                          "--out", os.path.join(d, "o.md")])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
