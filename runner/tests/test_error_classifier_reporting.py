"""The error data existed; there was no way to look at it.

error_classifier.track() has always recorded classified errors into a ring buffer, and
recent_errors() / error_rate() can query it — but nothing summarised it. So the gap this
slice names, "no real-time reporting or detailed logs for debugging", was real in a
specific way: an operator asking "what is failing right now, and is it one thing or many?"
had to read a hundred raw entries.

The split that makes the digest useful is retryable-vs-not. A burst of transient errors
and a burst of logic errors need opposite responses — wait, versus stop and fix — and a
bare total cannot tell them apart.
"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import error_classifier as ec  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    ec.reset_tracking()
    yield
    ec.reset_tracking()


class TestReport:
    def test_an_empty_ring_reports_zero_rather_than_failing(self):
        d = ec.report()
        assert d["total"] == 0
        assert d["by_category"] == {}

    def test_it_counts_what_was_tracked(self):
        ec.track("connection reset by peer")
        ec.track("429 rate limit")
        assert ec.report()["total"] == 2

    def test_it_groups_by_category(self):
        ec.track("connection reset by peer")
        ec.track("429 rate limit")
        ec.track("SyntaxError: invalid syntax")
        assert ec.report()["by_category"]["transient"] == 2

    def test_top_categories_are_ranked_by_count(self):
        for _ in range(3):
            ec.track("connection reset by peer")
        ec.track("SyntaxError: invalid syntax")
        assert ec.report()["top_categories"][0][0] == "transient"
        assert ec.report()["top_categories"][0][1] == 3

    def test_it_separates_self_clearing_from_the_rest(self):
        """The split that decides whether to wait or to stop and fix."""
        ec.track("connection reset by peer")   # transient
        ec.track("budget cap reached")         # resource
        ec.track("SyntaxError: invalid syntax")  # not self-clearing
        d = ec.report()
        assert d["retryable"] == 2
        assert d["total"] - d["retryable"] == 1

    def test_the_latest_entries_carry_their_context(self):
        ec.track("connection reset by peer", task_id="t1", hook="merge")
        latest = ec.report()["latest"][0]
        assert latest["task_id"] == "t1"
        assert latest["hook"] == "merge"
        assert "connection reset" in latest["message"]

    def test_older_errors_fall_outside_the_window(self):
        ec.track("connection reset by peer")
        ec._ring[0]["ts"] = time.time() - 10_000
        assert ec.report(window_secs=60)["total"] == 0

    def test_the_window_is_env_tunable(self):
        """ORCH_-prefixed per CLAUDE.md so fleet_control.py can push it."""
        assert isinstance(ec.REPORT_WINDOW_SECS, int)
        assert "ORCH_ERROR_REPORT_WINDOW_SECS" in open(ec.__file__, encoding="utf-8").read()

    def test_top_n_is_respected(self):
        for msg in ("connection reset", "budget cap", "SyntaxError: x", "permission denied"):
            ec.track(msg)
        assert len(ec.report(top_n=2)["top_categories"]) <= 2

    def test_it_never_raises_on_a_corrupted_ring(self, monkeypatch):
        monkeypatch.setattr(ec, "_ring", "not a list")
        d = ec.report()
        assert d["total"] == 0


class TestRenderReport:
    def test_a_quiet_window_says_so(self):
        assert "no errors" in ec.render_report()

    def test_it_names_the_split_in_the_headline(self):
        ec.track("connection reset by peer")
        ec.track("SyntaxError: invalid syntax")
        out = ec.render_report()
        assert "self-clearing" in out
        assert "2 error(s)" in out

    def test_it_lists_the_latest_with_severity_and_category(self):
        ec.track("connection reset by peer", hook="merge")
        out = ec.render_report()
        assert "transient" in out
        assert "merge" in out

    def test_it_accepts_a_prebuilt_digest(self):
        ec.track("connection reset by peer")
        assert ec.render_report(ec.report()).startswith("1 error(s)")

    @pytest.mark.parametrize("digest", [None, {}, {"total": "many"}, 7])
    def test_it_never_raises(self, digest):
        assert isinstance(ec.render_report(digest), str)


class TestReset:
    def test_it_clears_the_ring(self):
        ec.track("connection reset by peer")
        assert ec.report()["total"] == 1
        ec.reset_tracking()
        assert ec.report()["total"] == 0

    def test_tracking_still_works_after_a_reset(self):
        ec.reset_tracking()
        ec.track("connection reset by peer")
        assert ec.report()["total"] == 1


class TestExistingBehaviourUnchanged:
    def test_classify_is_untouched(self):
        assert ec.classify("connection reset by peer")["category"] == ec.TRANSIENT

    def test_track_still_returns_the_classification(self):
        assert ec.track("429 rate limit")["category"] == ec.TRANSIENT

    def test_recent_errors_still_works(self):
        ec.track("connection reset by peer")
        assert len(ec.recent_errors()) == 1

    def test_error_rate_still_works(self):
        ec.track("connection reset by peer")
        assert ec.error_rate() == 1
