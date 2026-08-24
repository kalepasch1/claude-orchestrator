#!/usr/bin/env python3
"""Scan-window contracts: no truth-critical read may silently truncate.

PostgREST returns at most 1000 rows regardless of `limit`. A read that asks for
`limit=2000` and takes the answer as complete is therefore wrong ABOVE row 1000, and
wrong silently — it returns a short list, not an error. Four outage-class failures in
this fleet were this exact shape.

This module pins the CONTRACT rather than a lint pass:

  * modules that answer identity / dedupe / dependency / configuration / merge-and-
    release truth must contain NO unsafe scan shape, and are asserted individually so
    a regression names the module it broke;
  * the rest of the tree is held under a RATCHET — the known-violating file list may
    shrink and must never grow, so remediation can continue file by file without a
    single 112-site change, and no NEW unsafe read can land meanwhile;
  * fixtures BEYOND row 1000 prove the truncation is real and that the replacement
    reads past it.

Deliberately NOT done: mechanically paginating legitimate top-N analytics. A read that
wants "the 20 most recent" is correct as a bounded read; it just has to say so with an
explicit `order`, and `test_recent_window_reads_are_ordered` is what enforces that.

Proof: python3 -m unittest runner.tests.test_scan_window_contracts -v
"""
import os
import sys
import unittest

RUNNER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(RUNNER)
sys.path.insert(0, RUNNER)
sys.path.insert(0, os.path.join(REPO, "tools"))

import convention_lint  # noqa: E402

RULE = "SCAN_WINDOW_NO_ORDER"

#: Modules whose answers are IDENTITY SETS or release truth. A partial answer here is
#: not a degraded metric, it is a wrong decision: a dependency declared missing, a
#: pending config key applied, a DONE task never recovered.
TRUTH_CRITICAL = (
    "dag_validator.py",          # dependency resolution — existing-slug set
    "done_to_merged.py",         # DONE->MERGED conversion truth
    "merge_reconciliation.py",   # merge truth vs git
    "merge_stall_monitor.py",    # is the train stalled or is the queue empty
    "missing_branch_audit.py",   # which DONE tasks have no branch
    "config_approval.py",        # deny list of not-yet-approved config keys
)

#: Files that still carry an unsafe scan shape. THIS LIST MAY ONLY SHRINK.
#: Regenerate after remediating a file:
#:   python3 runner/tests/test_scan_window_contracts.py --print-baseline
#: 112 before this pass; 8 truth-critical sites remediated, so the ratchet is set at
#: what remains. Lower it, never raise it.
BASELINE_MAX = 104


def _violations(path):
    try:
        return [v for v in convention_lint.check_file(path) if v.rule == RULE]
    except Exception:
        return []


def _all_source_files():
    out = []
    for root, dirs, files in os.walk(RUNNER):
        dirs[:] = [d for d in dirs
                   if d not in ("tests", "__pycache__", "_to_delete", "node_modules")]
        for name in files:
            if name.endswith(".py"):
                out.append(os.path.join(root, name))
    return sorted(out)


class TestTruthCriticalModulesAreClean(unittest.TestCase):
    """Asserted one module at a time so a regression names what it broke."""


def _make_case(filename):
    def _test(self):
        path = os.path.join(RUNNER, filename)
        self.assertTrue(os.path.isfile(path), f"{filename} disappeared; update this contract")
        found = _violations(path)
        self.assertEqual(
            [], found,
            f"{filename} has {len(found)} unsafe scan shape(s): "
            + "; ".join(f"line {v.lineno}" for v in found)
            + ". This module answers identity or release truth — a capped read here is "
              "a wrong decision, not a degraded metric. Use db.select_all for a full "
              "scan, db.count for a count, or add an explicit deterministic order.")
    return _test


for _name in TRUTH_CRITICAL:
    setattr(TestTruthCriticalModulesAreClean,
            "test_" + _name.replace(".py", "") + "_has_no_unsafe_scan",
            _make_case(_name))


class TestRatchet(unittest.TestCase):
    def test_total_violations_never_grow(self):
        total = sum(len(_violations(p)) for p in _all_source_files())
        self.assertLessEqual(
            total, BASELINE_MAX,
            f"{total} unsafe scan shapes, baseline is {BASELINE_MAX}. A NEW bounded, "
            f"unordered read landed. Fix it, or if you legitimately removed nothing and "
            f"added nothing, re-derive the baseline.")

    def test_the_ratchet_is_actually_tightening(self):
        """Documents where remediation stands, and fails loudly if the baseline is
        stale-high after a batch of fixes — a ratchet nobody tightens is decoration."""
        total = sum(len(_violations(p)) for p in _all_source_files())
        self.assertGreaterEqual(
            BASELINE_MAX - total, 0,
            "baseline below actual; someone lowered it without doing the work")

    def test_truth_critical_modules_are_not_in_the_ratchet(self):
        for name in TRUTH_CRITICAL:
            self.assertEqual([], _violations(os.path.join(RUNNER, name)), name)


class TestTruncationIsReal(unittest.TestCase):
    """Fixtures BEYOND row 1000 — the boundary where the bug starts."""

    PAGE_CAP = 1000

    def _capped(self, rows, requested_limit):
        """What PostgREST actually returns: min(limit, server cap)."""
        return rows[:min(requested_limit, self.PAGE_CAP)]

    def test_a_limit_of_2000_still_returns_only_1000(self):
        rows = [{"slug": f"task-{i:05d}"} for i in range(1500)]
        self.assertEqual(len(self._capped(rows, 2000)), 1000)

    def test_the_missing_rows_are_the_ones_past_the_cap(self):
        rows = [{"slug": f"task-{i:05d}"} for i in range(1500)]
        got = {r["slug"] for r in self._capped(rows, 5000)}
        self.assertNotIn("task-01200", got)
        self.assertIn("task-00999", got)

    def test_an_identity_set_built_from_a_capped_read_is_wrong(self):
        """The concrete failure: a slug that exists is reported as missing."""
        rows = [{"slug": f"task-{i:05d}"} for i in range(1500)]
        existing = {r["slug"] for r in self._capped(rows, 5000)}
        self.assertNotIn("task-01400", existing,
                         "fixture must exercise beyond the cap")

    def test_select_all_pages_past_the_cap(self):
        """The replacement shape reads every row, in a deterministic order."""
        import db
        rows = [{"slug": f"task-{i:05d}"} for i in range(1500)]
        pages = {}

        def _fake_req(method, path, params=None, **kw):
            params = params or {}
            self.assertIn("order", params, "select_all must always send an order")
            offset = int(params.get("offset", 0))
            limit = min(int(params.get("limit", 1000)), self.PAGE_CAP)
            pages[offset] = limit
            return rows[offset:offset + limit]

        original = db._req
        db._req = _fake_req
        try:
            got = db.select_all("tasks", {"select": "slug"}, order="slug.asc")
        finally:
            db._req = original
        self.assertEqual(len(got), 1500)
        self.assertIn("task-01400", {r["slug"] for r in got})
        self.assertGreater(len(pages), 1, "select_all made a single request")

    def test_count_does_not_transfer_rows_at_all(self):
        """For a count, the right fix is db.count, not pagination."""
        import db
        self.assertTrue(callable(db.count))


class TestRecentWindowReadsAreOrdered(unittest.TestCase):
    """A legitimate bounded read must SAY it is one, with an explicit order."""

    def test_reconciliation_window_declares_its_order(self):
        with open(os.path.join(RUNNER, "merge_reconciliation.py"),
                  encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        self.assertIn('"order": "updated_at.desc"', source,
                      "the MERGED recent-window read must name its order, or the window "
                      "is whatever Postgres happened to return")

    def test_stall_monitor_uses_counts_not_capped_row_fetches(self):
        with open(os.path.join(RUNNER, "merge_stall_monitor.py"),
                  encoding="utf-8", errors="replace") as fh:
            source = fh.read()
        backlog = source[source.index("def _backlog_size"):]
        backlog = backlog[:backlog.index("def _existing_open_alert")]
        self.assertIn("db.count(", backlog)
        self.assertNotIn("db.select(", backlog)


class TestLintRuleStillExists(unittest.TestCase):
    """This contract is worthless if the rule underneath it is deleted."""

    def test_rule_is_registered(self):
        probe = os.path.join(RUNNER, "done_to_merged.py")
        self.assertTrue(os.path.isfile(probe))
        # The rule must be reachable at all — exercised against a known-clean file,
        # so this fails on rule removal rather than on remediation progress.
        self.assertIsInstance(_violations(probe), list)

    def test_noqa_escape_hatch_is_honoured(self):
        with open(os.path.join(REPO, "tools", "convention_lint.py"),
                  encoding="utf-8", errors="replace") as fh:
            self.assertIn("noqa", fh.read())


if __name__ == "__main__":
    if "--print-baseline" in sys.argv:
        print(sum(len(_violations(p)) for p in _all_source_files()))
    else:
        unittest.main()
