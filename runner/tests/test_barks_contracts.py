"""Tests for barks_contracts — every dataclass instantiates, HumanGate defaults PENDING, Result defaults ok=False."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from barks_contracts import (
    Result, HumanGate, Hotel, Sponsor, VolunteerShift, PickupRun,
    ShelterSupplyMatch, ImpactReceipt, OutreachDraft, GrantApplication,
    HumanGateTask, DispatchEngine, OnboardingFlow, ImpactReportAssembler,
    EsgTargetingEngine, GrantAutopilot,
    ORCH_SB_MAX_PICKUP_STOPS, ORCH_SB_DEFAULT_SHIFT_HOURS, ORCH_SB_QUARTER_MONTHS,
)


class TestResult:
    def test_default_ok_false(self):
        r = Result()
        assert r.ok is False

    def test_default_value_none(self):
        assert Result().value is None

    def test_default_error_empty(self):
        assert Result().error == ""

    def test_success(self):
        r = Result(ok=True, value=42)
        assert r.ok is True and r.value == 42

    def test_failure_with_error(self):
        r = Result(ok=False, error="bad")
        assert r.error == "bad"


class TestHumanGate:
    def test_default_pending(self):
        assert HumanGate.PENDING.value == "PENDING"

    def test_approved(self):
        assert HumanGate.APPROVED.value == "APPROVED"

    def test_rejected(self):
        assert HumanGate.REJECTED.value == "REJECTED"

    def test_gate_task_defaults_pending(self):
        t = HumanGateTask()
        assert t.gate == HumanGate.PENDING


class TestDataclasses:
    def test_hotel(self):
        h = Hotel(id="h1", name="Test Hotel")
        assert h.id == "h1"

    def test_sponsor(self):
        s = Sponsor(id="s1", name="Acme", hotel_id="h1", amount_cents=5000)
        assert s.amount_cents == 5000

    def test_volunteer_shift(self):
        vs = VolunteerShift(id="v1", volunteer_name="Alice")
        assert vs.duration_hours == ORCH_SB_DEFAULT_SHIFT_HOURS

    def test_pickup_run(self):
        pr = PickupRun(id="p1", stops=[(1.0, 2.0)])
        assert len(pr.stops) == 1

    def test_shelter_supply_match(self):
        m = ShelterSupplyMatch(shelter_id="sh1", supply_type="toys", quantity=10)
        assert m.matched is False

    def test_impact_receipt(self):
        ir = ImpactReceipt(hotel_id="h1", quarter="2026-Q1")
        assert ir.toys_distributed == 0

    def test_outreach_draft(self):
        od = OutreachDraft(recipient="test@example.com", subject="Hi")
        assert od.body == ""

    def test_grant_application(self):
        ga = GrantApplication(id="g1", organization="TestOrg")
        assert ga.status == "draft"

    def test_human_gate_task(self):
        hgt = HumanGateTask(id="hg1", description="Review plan")
        assert hgt.gate == HumanGate.PENDING


class TestConfigConstants:
    def test_max_pickup_stops(self):
        assert isinstance(ORCH_SB_MAX_PICKUP_STOPS, int)

    def test_default_shift_hours(self):
        assert isinstance(ORCH_SB_DEFAULT_SHIFT_HOURS, int)

    def test_quarter_months(self):
        assert isinstance(ORCH_SB_QUARTER_MONTHS, int)
