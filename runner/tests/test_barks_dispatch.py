"""Tests for barks_dispatch — 20+ cases incl. edge cases."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from barks_contracts import VolunteerShift, HumanGate, ORCH_SB_MAX_PICKUP_STOPS
from barks_dispatch import SBDispatchEngine, WeeklyPlan


@pytest.fixture
def engine():
    return SBDispatchEngine()


class TestCreateShiftPayload:
    def test_basic(self, engine):
        s = VolunteerShift(id="v1", volunteer_name="Alice", date="2026-01-01", location="Park")
        r = engine.create_shift_payload(s)
        assert r.ok and r.value["volunteer"] == "Alice"

    def test_none_shift(self, engine):
        r = engine.create_shift_payload(None)
        assert not r.ok

    def test_payload_fields(self, engine):
        s = VolunteerShift(id="v2", volunteer_name="Bob", date="2026-02-01", start_hour=9, duration_hours=3, location="Shelter")
        r = engine.create_shift_payload(s)
        assert r.ok
        assert r.value["start_hour"] == 9
        assert r.value["duration_hours"] == 3


class TestBuildPickupRoute:
    def test_empty_coordinates(self, engine):
        r = engine.build_pickup_route([])
        assert r.ok and r.value.distance_km == 0.0

    def test_single_stop(self, engine):
        r = engine.build_pickup_route([(1.0, 2.0)])
        assert r.ok and len(r.value.stops) == 1 and r.value.distance_km == 0.0

    def test_two_stops(self, engine):
        r = engine.build_pickup_route([(0, 0), (3, 4)])
        assert r.ok and r.value.distance_km == 5.0

    def test_three_stops_nearest_neighbor(self, engine):
        r = engine.build_pickup_route([(0, 0), (10, 0), (1, 0)])
        assert r.ok and r.value.stops == [(0, 0), (1, 0), (10, 0)]

    def test_none_coordinates(self, engine):
        r = engine.build_pickup_route(None)
        assert not r.ok

    def test_invalid_coordinate(self, engine):
        r = engine.build_pickup_route([(1,)])
        assert not r.ok

    def test_exceeds_max_stops(self, engine):
        coords = [(i, i) for i in range(ORCH_SB_MAX_PICKUP_STOPS + 1)]
        r = engine.build_pickup_route(coords)
        assert not r.ok and "max stops" in r.error


class TestMatchSupplies:
    def test_basic_match(self, engine):
        supplies = [{"type": "toys", "quantity": 10}]
        needs = [{"shelter_id": "s1", "type": "toys", "quantity": 5}]
        r = engine.match_supplies(supplies, needs)
        assert r.ok and r.value[0].quantity == 5

    def test_no_match(self, engine):
        supplies = [{"type": "food", "quantity": 10}]
        needs = [{"shelter_id": "s1", "type": "toys", "quantity": 5}]
        r = engine.match_supplies(supplies, needs)
        assert r.ok and r.value[0].quantity == 0 and not r.value[0].matched

    def test_partial_match(self, engine):
        supplies = [{"type": "toys", "quantity": 3}]
        needs = [{"shelter_id": "s1", "type": "toys", "quantity": 5}]
        r = engine.match_supplies(supplies, needs)
        assert r.ok and r.value[0].quantity == 3

    def test_none_supplies(self, engine):
        r = engine.match_supplies(None, [])
        assert not r.ok

    def test_none_needs(self, engine):
        r = engine.match_supplies([], None)
        assert not r.ok

    def test_empty_both(self, engine):
        r = engine.match_supplies([], [])
        assert r.ok and r.value == []


class TestWeeklyPlan:
    def test_default_gate_pending(self, engine):
        r = engine.approve_weekly_plan({"shifts": [1], "runs": [2]})
        assert r.ok and r.value.gate == HumanGate.PENDING

    def test_unapproved_blocks_dispatch(self, engine):
        r = engine.approve_weekly_plan({"shifts": [1]})
        plan = r.value
        dr = engine.dispatch_if_approved(plan)
        assert not dr.ok and "not approved" in dr.error

    def test_approved_allows_dispatch(self, engine):
        r = engine.approve_weekly_plan({"shifts": [1]})
        plan = r.value
        plan.gate = HumanGate.APPROVED
        dr = engine.dispatch_if_approved(plan)
        assert dr.ok and dr.value["dispatched"] is True

    def test_none_plan(self, engine):
        r = engine.approve_weekly_plan(None)
        assert not r.ok

    def test_dispatch_none_plan(self, engine):
        r = engine.dispatch_if_approved(None)
        assert not r.ok
