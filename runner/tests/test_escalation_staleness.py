#!/usr/bin/env python3
"""Tests for escalation_staleness — expiry of unanswered playbook halts."""
import datetime as dt
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import escalation_staleness as es

NOW = dt.datetime(2026, 8, 13, 12, 0, 0, tzinfo=dt.timezone.utc)


def _task(slug="escalate-p1-queue-clearance-no-improvement", hours_old=1.0,
          state="QUEUED", approved=None):
    return {
        "id": slug,
        "slug": slug,
        "state": state,
        "created_at": (NOW - dt.timedelta(hours=hours_old)).isoformat(),
        "operator_approved_at": approved,
        "counsel_approved_at": None,
    }


class TestIsEscalation:
    def test_recognises_playbook_prefixes(self):
        assert es.is_escalation({"slug": "escalate-p1-queue-clearance"}) is True
        assert es.is_escalation({"slug": "human-decision-p1-halt-bypassed"}) is True

    def test_ignores_ordinary_work(self):
        assert es.is_escalation({"slug": "backlog-batch-beethoven-8296d8f"}) is False
        assert es.is_escalation({}) is False


class TestAgeHours:
    def test_computes_age(self):
        assert es.age_hours(_task(hours_old=5), now=NOW) == 5.0

    def test_unparseable_timestamp_is_zero_not_a_crash(self):
        assert es.age_hours({"created_at": "not-a-date"}, now=NOW) == 0.0
        assert es.age_hours({}, now=NOW) == 0.0

    def test_future_timestamp_clamped_to_zero(self):
        assert es.age_hours(_task(hours_old=-4), now=NOW) == 0.0


class TestClassifyEscalation:
    def test_fresh_within_window(self):
        r = es.classify_escalation(_task(hours_old=3), now=NOW,
                                   stale_hours=24, expire_hours=72)
        assert r["status"] == "fresh"

    def test_stale_after_stale_hours(self):
        r = es.classify_escalation(_task(hours_old=30), now=NOW,
                                   stale_hours=24, expire_hours=72)
        assert r["status"] == "stale"

    def test_abandoned_after_expire_hours(self):
        r = es.classify_escalation(_task(hours_old=78), now=NOW,
                                   stale_hours=24, expire_hours=72)
        assert r["status"] == "abandoned"
        assert r["age_hours"] == 78.0

    def test_operator_touch_counts_as_answered(self):
        r = es.classify_escalation(
            _task(hours_old=200, approved=NOW.isoformat()), now=NOW,
            stale_hours=24, expire_hours=72)
        assert r["status"] == "answered"
        assert r["answered"] is True

    def test_state_change_counts_as_answered(self):
        r = es.classify_escalation(_task(hours_old=200, state="DONE"), now=NOW,
                                   stale_hours=24, expire_hours=72)
        assert r["status"] == "answered"

    def test_the_real_nk73_case(self):
        """The escalation that stood 78h unanswered while the queue grew."""
        r = es.classify_escalation(
            _task(slug="escalate-p1-queue-clearance-no-improvement-20260810-nk73",
                  hours_old=78), now=NOW, stale_hours=24, expire_hours=72)
        assert r["status"] == "abandoned"


class TestHaltDecision:
    def test_no_escalations_means_no_halt(self):
        d = es.halt_decision([])
        assert d["honor_halt"] is False

    def test_fresh_escalation_keeps_halt(self):
        c = [es.classify_escalation(_task(hours_old=2), now=NOW,
                                    stale_hours=24, expire_hours=72)]
        assert es.halt_decision(c)["honor_halt"] is True

    def test_stale_escalation_still_keeps_halt(self):
        """Stale means 'shout louder', not 'give up' — a human may yet arrive."""
        c = [es.classify_escalation(_task(hours_old=30), now=NOW,
                                    stale_hours=24, expire_hours=72)]
        assert es.halt_decision(c)["honor_halt"] is True

    def test_abandoned_escalation_releases_halt(self):
        c = [es.classify_escalation(_task(hours_old=78), now=NOW,
                                    stale_hours=24, expire_hours=72)]
        d = es.halt_decision(c)
        assert d["honor_halt"] is False
        assert d["expired"]
        assert "remain queued" in d["reason"]

    def test_one_fresh_escalation_blocks_expiry_of_the_batch(self):
        c = [
            es.classify_escalation(_task(slug="escalate-old", hours_old=200),
                                   now=NOW, stale_hours=24, expire_hours=72),
            es.classify_escalation(_task(slug="escalate-new", hours_old=1),
                                   now=NOW, stale_hours=24, expire_hours=72),
        ]
        d = es.halt_decision(c)
        assert d["honor_halt"] is True
        assert d["expired"] == []
        assert "escalate-new" in d["blocking"]

    def test_answered_escalations_do_not_hold_the_halt(self):
        c = [es.classify_escalation(_task(hours_old=200, state="DONE"), now=NOW,
                                    stale_hours=24, expire_hours=72)]
        assert es.halt_decision(c)["honor_halt"] is False

    def test_expiry_can_be_disabled(self):
        c = [es.classify_escalation(_task(hours_old=500), now=NOW,
                                    stale_hours=24, expire_hours=72)]
        d = es.halt_decision(c, expiry_enabled=False)
        assert d["honor_halt"] is True
        assert "disabled" in d["reason"]


class TestRunFailSoft:
    def test_db_failure_yields_empty_report_not_a_crash(self):
        with patch.object(es.db, "select", side_effect=RuntimeError("DB down")):
            r = es.run(dry_run=True)
        assert r["checked"] == 0
        assert r["honor_halt"] is False

    def test_dry_run_writes_nothing(self):
        rows = [_task(hours_old=100)]
        with patch.object(es.db, "select") as sel, \
             patch.object(es.db, "insert") as ins:
            def select_side_effect(table, params=None):
                return rows if table == "tasks" else []
            sel.side_effect = select_side_effect
            r = es.run(dry_run=True)
            assert ins.called is False
        assert r["alerts_opened"] == 1
        assert r["counts"]["abandoned"] == 1
        assert r["honor_halt"] is False

    def test_alert_is_not_duplicated(self):
        rows = [_task(hours_old=100)]
        with patch.object(es.db, "select") as sel, \
             patch.object(es.db, "insert") as ins:
            def select_side_effect(table, params=None):
                if table == "tasks":
                    return rows
                return [{"id": "existing-alert"}]  # alert already open
            sel.side_effect = select_side_effect
            r = es.run()
            assert ins.called is False
        assert r["alerts_opened"] == 0

    def test_alert_write_failure_is_survivable(self):
        rows = [_task(hours_old=100)]
        with patch.object(es.db, "select") as sel, \
             patch.object(es.db, "insert", side_effect=RuntimeError("write failed")):
            def select_side_effect(table, params=None):
                return rows if table == "tasks" else []
            sel.side_effect = select_side_effect
            r = es.run()
        assert r["alerts_opened"] == 0
        assert r["checked"] == 1


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
