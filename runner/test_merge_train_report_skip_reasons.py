"""Skip-reason accounting for the merge train pass report.

Regression cover for the silent-failure class behind "0 merged, 581 skipped"
(operator, 2026-07-31): the pass report recorded a reason string per skipped
branch but never aggregated them, and `skipped_reasons` truncates to 50 slugs.
A 581-skip pass therefore reported a bare count and 50 arbitrary slugs, so the
train sat broken from Jul 28 with no visible cause.

These tests assert the breakdown exists, is uncapped, and reaches both the
summary JSON and the log line.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

merge_train_report = pytest.importorskip("merge_train_report")
PassReport = merge_train_report.PassReport


def _report(**kw):
    return PassReport(**kw)


def test_skipped_by_reason_counts_each_class():
    r = _report(trigger="test")
    r.skipped("a", "no_approved_card: nothing approved")
    r.skipped("b", "no_approved_card: nothing approved")
    r.skipped("c", "verify_pending: awaiting verify")
    assert r.skipped_by_reason() == {"no_approved_card": 2, "verify_pending": 1}


def test_breakdown_is_sorted_by_count_desc_then_name():
    r = _report(trigger="test")
    for i in range(3):
        r.skipped(f"x{i}", "stale: old")
    r.skipped("y", "waiting_window: outside window")
    r.skipped("z", "already_merged_content: base has it")
    assert list(r.skipped_by_reason()) == [
        "stale", "already_merged_content", "waiting_window"]


def test_breakdown_is_not_truncated_at_fifty():
    """`skipped_reasons` caps at 50 slugs; the histogram must not inherit that."""
    r = _report(trigger="test")
    for i in range(581):
        r.skipped(f"slug-{i}", "waiting_window: release flag false")
    d = r.to_dict()
    assert d["skipped"] == 581
    assert len(d["skipped_reasons"]) == 50           # documents the cap
    assert d["skipped_by_reason"] == {"waiting_window": 581}  # and that we bypass it


def test_reason_without_colon_still_classified():
    r = _report(trigger="test")
    r.skipped("a", "stale")
    r.skipped("b", "")
    hist = r.skipped_by_reason()
    assert hist["stale"] == 1
    assert hist["unspecified"] == 1


def test_failed_and_skipped_are_accounted_separately():
    r = _report(trigger="test")
    r.skipped("a", "stale: old")
    r.failed("b", "testfail: 3 failing")
    assert r.skipped_by_reason() == {"stale": 1}
    assert r.failed_by_reason() == {"testfail": 1}
    assert r.blocked_by_reason() == {"stale": 1, "testfail": 1}


def test_merged_branch_is_dropped_from_skip_accounting():
    """merged() clears prior skip/fail state; the histogram must follow."""
    r = _report(trigger="test")
    r.skipped("a", "waiting_window: outside window")
    r.merged("a")
    assert r.skipped_by_reason() == {}
    assert r.to_dict()["skipped_by_reason"] == {}


def test_summary_line_shows_skip_breakdown_on_a_partial_pass():
    """A pass that merges something still has to explain its skips."""
    r = _report(trigger="test")
    r.merged("ok")
    for i in range(4):
        r.skipped(f"s{i}", "no_approved_card: nothing approved")
    line = r.summary_line()
    assert "4 skipped" in line
    assert "skips:" in line
    assert "no_approved_card=4" in line
    assert "MERGED NOTHING" not in line


def test_summary_line_omits_breakdown_when_nothing_skipped():
    r = _report(trigger="test")
    r.merged("ok")
    line = r.summary_line()
    assert "skips:" not in line
    assert "fails:" not in line


def test_no_op_reason_uses_the_shared_histogram():
    r = _report(trigger="test")
    r.skipped("a", "stale: old")
    r.skipped("b", "stale: old")
    r.failed("c", "conflict: rebase failed")
    reason = r.no_op_reason()
    assert reason.startswith("all-cards-blocked: ")
    assert "stale=2" in reason
    assert "conflict=1" in reason


def test_no_op_reason_precedence_is_preserved():
    """not_run and unaccounted still outrank the blocked breakdown."""
    r = _report(trigger="test")
    r.not_run("paused")
    assert r.no_op_reason() == "paused"

    r2 = _report(trigger="test")
    r2.consider("orphan")
    assert r2.no_op_reason().startswith("unaccounted:")


def test_empty_pass_reports_no_cards():
    r = _report(trigger="test")
    assert r.no_op_reason() == "no-cards"
    assert r.to_dict()["skipped_by_reason"] == {}
