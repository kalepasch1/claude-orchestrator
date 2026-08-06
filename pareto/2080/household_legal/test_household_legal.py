"""household_legal: fail-soft consumption, regime-aware updates, tier escalation.

Includes the required INTEGRATION test where one fixture regime event flows
regime_consumer -> doc_updater -> subscription_tier in a single test.
"""
import os
import sys

import pytest

# '2080' is not a valid Python identifier — same sys.path convention as
# pareto/2080/contracts/test_contracts_smoke.py.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import doc_updater as du  # noqa: E402
import regime_consumer as rc  # noqa: E402
import subscription_tier as st  # noqa: E402


FIXTURE_EVENT = {"regime": "CA", "effective_date": "2026-09-01"}


class StubOracle:
    """Minimal RegimeOracle stand-in."""

    def __init__(self, events=None, raises=False):
        self._events = events or []
        self._raises = raises
        self.subscribed = []

    def get_events(self, jurisdiction):
        if self._raises:
            raise RuntimeError("oracle unavailable")
        return list(self._events)

    def subscribe(self, jurisdiction, callback):
        if self._raises:
            raise RuntimeError("oracle unavailable")
        self.subscribed.append((jurisdiction, callback))


# ── (1) regime_consumer fail-soft on oracle unavailability ───────────────────

def test_consume_returns_empty_when_oracle_raises():
    assert rc.safe_consume_regime_event(StubOracle(raises=True), "CA") == []


def test_consume_returns_empty_when_there_is_no_oracle():
    assert rc.safe_consume_regime_event(None, "CA") == []


def test_consume_returns_empty_when_oracle_lacks_get_events():
    assert rc.safe_consume_regime_event(object(), "CA") == []


def test_consume_survives_a_non_iterable_oracle_response():
    class Weird:
        def get_events(self, jurisdiction):
            return 42

    assert rc.safe_consume_regime_event(Weird(), "CA") == []


def test_consume_drops_unusable_events_rather_than_inventing_one():
    """A fabricated event would rewrite a document off nothing at all."""
    oracle = StubOracle(events=[{"no_jurisdiction": True}, None, FIXTURE_EVENT])

    events = rc.safe_consume_regime_event(oracle, "CA")

    assert len(events) == 1
    assert events[0]["jurisdiction"] == "CA"


def test_normalize_accepts_both_jurisdiction_and_regime_spellings():
    assert rc.normalize_regime_event({"jurisdiction": "NY"})["jurisdiction"] == "NY"
    assert rc.normalize_regime_event({"regime": "NY"})["jurisdiction"] == "NY"
    assert rc.normalize_regime_event({"regime": "  "}) is None


def test_normalize_accepts_a_dataclass_style_event():
    class Event:
        def __init__(self):
            self.jurisdiction = "TX"
            self.effective_date = "2026-01-01"

    assert rc.normalize_regime_event(Event())["jurisdiction"] == "TX"


def test_subscribe_is_fail_soft():
    assert rc.safe_subscribe(StubOracle(raises=True), "CA", "cb") is False
    assert rc.safe_subscribe(object(), "CA", "cb") is False
    ok_oracle = StubOracle()
    assert rc.safe_subscribe(ok_oracle, "CA", "cb") is True
    assert ok_oracle.subscribed == [("CA", "cb")]


# ── (2) doc_updater: regime event -> template update + notification ──────────

def test_update_lease_template_applies_regime_clauses():
    updater = du.DocumentUpdater()

    ok, template = updater.update_lease_template(FIXTURE_EVENT)

    assert ok is True
    assert "CA REGIME CLAUSES" in template
    assert "60 days written notice" in template
    assert "2026-09-01" in template


def test_update_lease_template_handles_a_dict_template():
    updater = du.DocumentUpdater()

    ok, template = updater.update_lease_template(FIXTURE_EVENT, {"title": "Lease"})

    assert ok is True
    assert template["regime"] == "CA"
    assert template["effective_date"] == "2026-09-01"
    assert "notice_period" in template["clauses"]
    assert template["title"] == "Lease", "existing fields must be preserved"


def test_a_failed_update_returns_the_original_template_untouched():
    """A partial rewrite is worse than none — a user would sign it believing
    it was updated."""
    updater = du.DocumentUpdater()
    original = "ORIGINAL TEXT"

    for bad in (None, {}, {"regime": "  "}, {"regime": "ZZ"}):
        ok, template = updater.update_lease_template(bad, original)
        assert ok is False
        assert template == original


def test_fire_notification_queues_and_never_raises():
    updater = du.DocumentUpdater()

    updater.fire_notification("user-1", "lease updated")
    updater.fire_notification(None, None)

    assert updater.notification_queue[0] == {
        "user_id": "user-1", "change_summary": "lease updated"}
    assert len(updater.notification_queue) == 2


def test_process_jurisdiction_updates_and_notifies():
    updater = du.DocumentUpdater(oracle=StubOracle(events=[FIXTURE_EVENT]))

    ok, template = updater.process_jurisdiction("CA", "user-1")

    assert ok is True
    assert "CA REGIME CLAUSES" in template
    assert len(updater.notification_queue) == 1
    assert "CA" in updater.notification_queue[0]["change_summary"]


def test_process_jurisdiction_is_fail_soft_when_the_oracle_is_down():
    updater = du.DocumentUpdater(oracle=StubOracle(raises=True))

    ok, template = updater.process_jurisdiction("CA", "user-1")

    assert ok is False
    assert updater.notification_queue == [], "no notification on a failed update"


# ── (3) subscription_tier threshold logic ────────────────────────────────────

def test_usage_within_the_limit_does_not_escalate():
    result = st.evaluate_tier("standard", regime_update_count=5)

    assert result.escalate is False
    assert result.recommended_tier == "standard"


def test_usage_over_the_limit_escalates_one_step():
    result = st.evaluate_tier("free", regime_update_count=5)

    assert result.escalate is True
    assert result.recommended_tier == "standard"


def test_a_complex_jurisdiction_raises_the_floor():
    result = st.evaluate_tier("free", regime_update_count=0, jurisdictions=["CA"])

    assert result.escalate is True
    assert result.recommended_tier == "standard"
    assert "requires at least standard" in " ".join(result.reasons)


def test_an_unknown_tier_reads_as_the_lowest_not_the_highest():
    """Failing upward would grant paid entitlements on a typo."""
    assert st.normalize_tier("premiumm") == "free"
    assert st.normalize_tier(None) == "free"
    assert st.evaluate_tier("nonsense", regime_update_count=0).current_tier == "free"


def test_premium_is_never_escalated_past():
    result = st.evaluate_tier("premium", regime_update_count=999, jurisdictions=["CA"])

    assert result.escalate is False
    assert result.recommended_tier == "premium"


def test_malformed_usage_counts_are_treated_as_zero_not_as_a_crash():
    for bad in (None, "many", -5):
        assert st.evaluate_tier("free", regime_update_count=bad).usage == 0


# ── (4) INTEGRATION: one event through all three modules ─────────────────────

def test_integration_regime_event_flows_through_the_whole_stack():
    oracle = StubOracle(events=[FIXTURE_EVENT])
    updater = du.DocumentUpdater(oracle=oracle)

    # regime_consumer
    events = rc.safe_consume_regime_event(oracle, "CA")
    assert len(events) == 1
    assert events[0]["jurisdiction"] == "CA"
    assert events[0]["effective_date"] == "2026-09-01"

    # doc_updater — template updated AND notification fired
    ok, template = updater.update_lease_template(events[0])
    assert ok is True
    assert "60 days written notice" in template
    updater.fire_notification("user-42", "Lease template updated for CA")
    assert updater.notification_queue == [
        {"user_id": "user-42", "change_summary": "Lease template updated for CA"}]

    # subscription_tier — escalation evaluated off the same event
    evaluation = st.evaluate_tier(
        "free",
        regime_update_count=len(events),
        jurisdictions=[e["jurisdiction"] for e in events],
    )
    assert evaluation.escalate is True
    assert evaluation.recommended_tier == "standard"


def test_integration_oracle_outage_degrades_the_whole_stack_softly():
    oracle = StubOracle(raises=True)
    updater = du.DocumentUpdater(oracle=oracle)

    events = rc.safe_consume_regime_event(oracle, "CA")
    ok, _template = updater.process_jurisdiction("CA", "user-42")
    evaluation = st.evaluate_tier("free", regime_update_count=len(events))

    assert events == []
    assert ok is False
    assert updater.notification_queue == []
    assert evaluation.escalate is False, "no usage observed means no escalation"


# ── get_regime_oracle / dual-arity safe_consume_regime_event ─────────────────

def test_get_regime_oracle_degrades_to_a_no_op_rather_than_none():
    oracle = rc.get_regime_oracle()

    assert oracle is not None
    assert oracle.get_events("CA") == []
    assert oracle.subscribe("CA", "cb") is None
    assert getattr(oracle, "available", None) is False, \
        "a caller must be able to tell a dead feed from a quiet jurisdiction"


@pytest.mark.parametrize("factory", [
    lambda: None,                       # factory returns None
    lambda: (_ for _ in ()).throw(RuntimeError("boom")),   # factory raises
])
def test_get_regime_oracle_handles_every_unavailability_shape(factory):
    assert isinstance(rc.get_regime_oracle(factory), rc.NoOpRegimeOracle)


def test_get_regime_oracle_returns_a_supplied_oracle():
    stub = StubOracle()
    assert rc.get_regime_oracle(lambda: stub) is stub
    assert rc.get_regime_oracle(stub) is stub


def test_safe_consume_single_argument_form_returns_a_dict():
    """The sibling slice's acceptance shape."""
    assert rc.safe_consume_regime_event(FIXTURE_EVENT)["jurisdiction"] == "CA"
    assert rc.safe_consume_regime_event(None) == {}
    assert rc.safe_consume_regime_event({"regime": "  "}) == {}


def test_safe_consume_two_argument_form_still_returns_a_list():
    assert rc.safe_consume_regime_event(StubOracle(events=[FIXTURE_EVENT]), "CA") == \
        rc.consume_oracle_events(StubOracle(events=[FIXTURE_EVENT]), "CA")
    assert rc.safe_consume_regime_event(StubOracle(raises=True), "CA") == []


# ── SubscriptionTierMonitor ──────────────────────────────────────────────────

BREACH_EVENT = {"regime": "CA", "rule_id": "breach-001",
                "description": "tenant deposit rule breach"}


def test_free_tier_breach_escalates():
    monitor = st.SubscriptionTierMonitor()

    assert monitor.check_remediation_threshold("free", BREACH_EVENT) is True


def test_paid_tier_breach_does_not_escalate():
    """A paid tier gets in-house remediation; escalating would sell them what
    they already bought."""
    monitor = st.SubscriptionTierMonitor()

    assert monitor.check_remediation_threshold("standard", BREACH_EVENT) is False
    assert monitor.check_remediation_threshold("premium", BREACH_EVENT) is False


def test_a_non_breach_event_never_escalates():
    monitor = st.SubscriptionTierMonitor()

    assert monitor.check_remediation_threshold("free", FIXTURE_EVENT) is False


def test_threshold_check_fails_soft_to_no_escalation():
    """Fail-soft returns False: a wrongly disclosed case cannot be recalled,
    while a missed breach resurfaces on the next event."""
    monitor = st.SubscriptionTierMonitor()

    for bad in (None, {}, {"regime": "  "}, object()):
        assert monitor.check_remediation_threshold("free", bad) is False


def test_escalation_queues_the_case_and_never_raises():
    monitor = st.SubscriptionTierMonitor()

    monitor.escalate_to_licensed_partners("user-9", "deposit breach")
    monitor.escalate_to_licensed_partners(None, None)

    assert monitor.partner_queue[0] == {
        "user_id": "user-9", "case_summary": "deposit breach"}
    assert len(monitor.partner_queue) == 2


def test_acceptance_free_escalates_paid_does_not():
    """The task's stated acceptance, end to end."""
    monitor = st.SubscriptionTierMonitor()

    if monitor.check_remediation_threshold("free", BREACH_EVENT):
        monitor.escalate_to_licensed_partners("free-user", "breach")
    if monitor.check_remediation_threshold("premium", BREACH_EVENT):
        monitor.escalate_to_licensed_partners("paid-user", "breach")

    assert [c["user_id"] for c in monitor.partner_queue] == ["free-user"]


def test_package_exports_are_importable_as_pareto_household_legal():
    from pareto.household_legal import (  # noqa: F401
        DocumentUpdater, SubscriptionTierMonitor, get_regime_oracle,
        safe_consume_regime_event,
    )

    assert isinstance(safe_consume_regime_event(None), dict)
