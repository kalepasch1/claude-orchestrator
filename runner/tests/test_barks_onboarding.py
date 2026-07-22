"""Tests for barks_onboarding — end-to-end + 15+ edge cases."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from barks_contracts import Hotel
from barks_onboarding import SBOnboardingFlow, OnboardingStage, _generate_qr_tag


@pytest.fixture
def flow():
    return SBOnboardingFlow()

@pytest.fixture
def hotel():
    return Hotel(id="h1", name="Test Hotel")


class TestHappyPath:
    def test_full_flow(self, flow, hotel):
        r = flow.start(hotel)
        assert r.ok and r.value.stage == OnboardingStage.LANDING

        r = flow.sign_sponsorship("h1")
        assert r.ok and r.value.signed and r.value.stage == OnboardingStage.ESIGN

        r = flow.ship_starter_kit("h1")
        assert r.ok and r.value.kit_shipped and r.value.stage == OnboardingStage.SHIP_KIT

        r = flow.generate_qr_tags("h1", 3)
        assert r.ok and len(r.value.qr_tags) == 3 and r.value.stage == OnboardingStage.QR_TAGS

        r = flow.report_distribution("h1", {"toy_a": 10, "toy_b": 5})
        assert r.ok and r.value.stage == OnboardingStage.REPORTING


class TestSkipStage:
    def test_skip_sign(self, flow, hotel):
        flow.start(hotel)
        r = flow.ship_starter_kit("h1")
        assert not r.ok and "expected stage" in r.error

    def test_skip_to_qr(self, flow, hotel):
        flow.start(hotel)
        r = flow.generate_qr_tags("h1", 5)
        assert not r.ok

    def test_skip_to_report(self, flow, hotel):
        flow.start(hotel)
        r = flow.report_distribution("h1", {})
        assert not r.ok


class TestReplayIdempotent:
    def test_start_idempotent(self, flow, hotel):
        r1 = flow.start(hotel)
        r2 = flow.start(hotel)
        assert r1.ok and r2.ok
        assert r1.value is r2.value  # same object


class TestEdgeCases:
    def test_none_hotel(self, flow):
        r = flow.start(None)
        assert not r.ok

    def test_unknown_hotel_sign(self, flow):
        r = flow.sign_sponsorship("unknown")
        assert not r.ok

    def test_unknown_hotel_ship(self, flow):
        r = flow.ship_starter_kit("unknown")
        assert not r.ok

    def test_negative_toy_count(self, flow, hotel):
        flow.start(hotel)
        flow.sign_sponsorship("h1")
        flow.ship_starter_kit("h1")
        r = flow.generate_qr_tags("h1", -1)
        assert not r.ok

    def test_zero_toy_count(self, flow, hotel):
        flow.start(hotel)
        flow.sign_sponsorship("h1")
        flow.ship_starter_kit("h1")
        r = flow.generate_qr_tags("h1", 0)
        assert r.ok and r.value.qr_tags == []

    def test_none_counts(self, flow, hotel):
        flow.start(hotel)
        flow.sign_sponsorship("h1")
        flow.ship_starter_kit("h1")
        flow.generate_qr_tags("h1", 2)
        r = flow.report_distribution("h1", None)
        assert not r.ok


class TestQRDeterminism:
    def test_same_input_same_output(self):
        a = _generate_qr_tag("h1", 0)
        b = _generate_qr_tag("h1", 0)
        assert a == b

    def test_different_index(self):
        a = _generate_qr_tag("h1", 0)
        b = _generate_qr_tag("h1", 1)
        assert a != b

    def test_different_hotel(self):
        a = _generate_qr_tag("h1", 0)
        b = _generate_qr_tag("h2", 0)
        assert a != b


class TestDistributionAggregation:
    def test_counts_stored(self, flow, hotel):
        flow.start(hotel)
        flow.sign_sponsorship("h1")
        flow.ship_starter_kit("h1")
        flow.generate_qr_tags("h1", 2)
        r = flow.report_distribution("h1", {"a": 5, "b": 3})
        assert r.ok
        assert r.value.distribution_counts == {"a": 5, "b": 3}

    def test_total_aggregation(self, flow, hotel):
        flow.start(hotel)
        flow.sign_sponsorship("h1")
        flow.ship_starter_kit("h1")
        flow.generate_qr_tags("h1", 2)
        r = flow.report_distribution("h1", {"a": 5, "b": 3})
        total = sum(r.value.distribution_counts.values())
        assert total == 8
