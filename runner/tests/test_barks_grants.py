"""Tests for barks_grants.py — 20+ cases covering drafting, gates, and submission."""
from __future__ import annotations

import os
import sys
import pytest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from barks_contracts import (
    GiftOpportunity,
    GrantApplication,
    HumanGateTask,
    Result,
)
from barks_grants import GrantAutopilot


# -- fixtures --------------------------------------------------------------

@pytest.fixture
def autopilot():
    return GrantAutopilot(now=date(2026, 7, 12))


@pytest.fixture
def sample_opportunities():
    return [
        GiftOpportunity(name="Late Grant", deadline=date(2026, 12, 1), requirements=["budget"]),
        GiftOpportunity(name="Early Grant", deadline=date(2026, 8, 1), requirements=["narrative", "timeline"]),
        GiftOpportunity(name="Mid Grant", deadline=date(2026, 10, 15)),
    ]


# -- Application assembly --------------------------------------------------

class TestDraftApplications:
    def test_basic_drafting(self, autopilot, sample_opportunities):
        result = autopilot.draft_applications(sample_opportunities)
        assert result.ok is True
        assert len(result.data) == 3

    def test_deadline_ordering_earliest_first(self, autopilot, sample_opportunities):
        result = autopilot.draft_applications(sample_opportunities)
        deadlines = [a.deadline for a in result.data]
        assert deadlines == sorted(deadlines)
        assert result.data[0].opportunity_name == "Early Grant"
        assert result.data[-1].opportunity_name == "Late Grant"

    def test_draft_text_contains_opportunity_name(self, autopilot):
        opps = [GiftOpportunity(name="Foo Fund", deadline=date(2026, 9, 1))]
        result = autopilot.draft_applications(opps)
        assert "Foo Fund" in result.data[0].draft_text

    def test_draft_text_contains_requirements(self, autopilot):
        opps = [GiftOpportunity(name="X", deadline=date(2026, 9, 1), requirements=["a", "b"])]
        result = autopilot.draft_applications(opps)
        assert "a, b" in result.data[0].draft_text

    def test_draft_text_no_requirements(self, autopilot):
        opps = [GiftOpportunity(name="X", deadline=date(2026, 9, 1))]
        result = autopilot.draft_applications(opps)
        assert "none specified" in result.data[0].draft_text

    def test_single_opportunity(self, autopilot):
        opps = [GiftOpportunity(name="Solo", deadline=date(2026, 11, 1))]
        result = autopilot.draft_applications(opps)
        assert result.ok and len(result.data) == 1

    def test_applications_start_not_submittable(self, autopilot, sample_opportunities):
        result = autopilot.draft_applications(sample_opportunities)
        for app in result.data:
            assert app.submittable is False

    def test_applications_start_with_no_gates(self, autopilot, sample_opportunities):
        result = autopilot.draft_applications(sample_opportunities)
        for app in result.data:
            assert app.gates == []


# -- None / empty input handling --------------------------------------------

class TestNoneAndEmptyInput:
    def test_none_opportunities(self, autopilot):
        result = autopilot.draft_applications(None)
        assert result.ok is True
        assert result.data == []

    def test_empty_list_opportunities(self, autopilot):
        result = autopilot.draft_applications([])
        assert result.ok is True
        assert result.data == []


# -- add_gate ---------------------------------------------------------------

class TestAddGate:
    def test_add_gate_basic(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        result = autopilot.add_gate(app, "Legal review")
        assert result.ok is True
        assert len(app.gates) == 1
        assert app.gates[0].description == "Legal review"
        assert app.gates[0].status == "PENDING"

    def test_add_multiple_gates(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        autopilot.add_gate(app, "Legal")
        autopilot.add_gate(app, "Finance")
        autopilot.add_gate(app, "Board")
        assert len(app.gates) == 3

    def test_add_gate_none_application(self, autopilot):
        result = autopilot.add_gate(None, "Legal review")
        assert result.ok is False
        assert "None" in result.error

    def test_add_gate_empty_description(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        result = autopilot.add_gate(app, "")
        assert result.ok is False
        assert "empty" in result.error


# -- check_submittable ------------------------------------------------------

class TestCheckSubmittable:
    def test_no_gates_is_submittable(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        assert autopilot.check_submittable(app) is True

    def test_pending_gate_blocks(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="Review", status="PENDING"))
        assert autopilot.check_submittable(app) is False

    def test_denied_gate_blocks(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="Review", status="DENIED"))
        assert autopilot.check_submittable(app) is False

    def test_all_approved_allows(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="APPROVED"))
        app.gates.append(HumanGateTask(description="B", status="APPROVED"))
        assert autopilot.check_submittable(app) is True

    def test_mixed_gates_blocks(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="APPROVED"))
        app.gates.append(HumanGateTask(description="B", status="PENDING"))
        assert autopilot.check_submittable(app) is False

    def test_none_application(self, autopilot):
        assert autopilot.check_submittable(None) is False


# -- mark_submittable -------------------------------------------------------

class TestMarkSubmittable:
    def test_all_approved_sets_submittable(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="APPROVED"))
        result = autopilot.mark_submittable(app)
        assert result.ok is True
        assert app.submittable is True

    def test_pending_gate_fails_closed(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="PENDING"))
        result = autopilot.mark_submittable(app)
        assert result.ok is False
        assert "pending" in result.error
        assert app.submittable is False

    def test_denied_gate_fails(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="DENIED"))
        result = autopilot.mark_submittable(app)
        assert result.ok is False
        assert "denied" in result.error
        assert app.submittable is False

    def test_no_gates_marks_submittable(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        result = autopilot.mark_submittable(app)
        assert result.ok is True
        assert app.submittable is True

    def test_none_application_fails(self, autopilot):
        result = autopilot.mark_submittable(None)
        assert result.ok is False

    def test_mark_then_check_consistency(self, autopilot):
        app = GrantApplication(opportunity_name="X", deadline=date(2026, 9, 1))
        app.gates.append(HumanGateTask(description="A", status="APPROVED"))
        autopilot.mark_submittable(app)
        assert autopilot.check_submittable(app) is True
        assert app.submittable is True


# -- Injectable now parameter -----------------------------------------------

class TestInjectableNow:
    def test_custom_now(self):
        ap = GrantAutopilot(now=date(2025, 1, 1))
        assert ap._now == date(2025, 1, 1)

    def test_default_now(self):
        ap = GrantAutopilot()
        assert ap._now == date.today()


# -- Multiple applications with mixed gate states ---------------------------

class TestMultipleApplicationsMixedGates:
    def test_batch_with_mixed_states(self, autopilot, sample_opportunities):
        result = autopilot.draft_applications(sample_opportunities)
        apps = result.data

        # app 0: all approved
        autopilot.add_gate(apps[0], "Legal")
        apps[0].gates[0].status = "APPROVED"

        # app 1: one pending
        autopilot.add_gate(apps[1], "Board")

        # app 2: no gates

        assert autopilot.check_submittable(apps[0]) is True
        assert autopilot.check_submittable(apps[1]) is False
        assert autopilot.check_submittable(apps[2]) is True

        r0 = autopilot.mark_submittable(apps[0])
        r1 = autopilot.mark_submittable(apps[1])
        r2 = autopilot.mark_submittable(apps[2])

        assert r0.ok is True and apps[0].submittable is True
        assert r1.ok is False and apps[1].submittable is False
        assert r2.ok is True and apps[2].submittable is True
