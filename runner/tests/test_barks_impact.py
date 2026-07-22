"""Tests for barks_impact — 20+ cases: full report, missing metrics, signature stability, renewal."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from barks_impact import SBImpactReportAssembler, _content_hash, _canonical_json


@pytest.fixture
def assembler():
    return SBImpactReportAssembler()


class TestAssembleReceipt:
    def test_full_report(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {
            "toys_distributed": 100, "shelter_hours": 50.5, "press_mentions": 3
        })
        assert r.ok
        assert r.value.toys_distributed == 100
        assert r.value.shelter_hours == 50.5
        assert r.value.press_mentions == 3

    def test_missing_toys(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {"shelter_hours": 10})
        assert r.ok and r.value.toys_distributed == 0

    def test_missing_hours(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 5})
        assert r.ok and r.value.shelter_hours == 0.0

    def test_missing_press(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 5, "shelter_hours": 2})
        assert r.ok and r.value.press_mentions == 0

    def test_all_missing(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {})
        assert r.ok and r.value.toys_distributed == 0 and r.value.shelter_hours == 0.0

    def test_none_metrics(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", None)
        assert r.ok and r.value.toys_distributed == 0

    def test_none_hotel_id(self, assembler):
        r = assembler.assemble_receipt(None, "2026-Q1", {})
        assert not r.ok

    def test_none_quarter(self, assembler):
        r = assembler.assemble_receipt("h1", None, {})
        assert not r.ok

    def test_signature_present(self, assembler):
        r = assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 10})
        assert r.ok and len(r.value.signature) == 64


class TestSignatureStability:
    def test_same_data_same_sig(self, assembler):
        m = {"toys_distributed": 10, "shelter_hours": 5, "press_mentions": 1}
        r1 = assembler.assemble_receipt("h1", "2026-Q1", m)
        # Fresh assembler for independent test
        a2 = SBImpactReportAssembler()
        r2 = a2.assemble_receipt("h1", "2026-Q1", m)
        assert r1.value.signature == r2.value.signature

    def test_different_data_different_sig(self, assembler):
        r1 = assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 10})
        a2 = SBImpactReportAssembler()
        r2 = a2.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 11})
        assert r1.value.signature != r2.value.signature

    def test_stable_across_key_reorderings(self):
        d1 = {"toys_distributed": 10, "shelter_hours": 5, "press_mentions": 1, "hotel_id": "h1", "quarter": "Q1"}
        d2 = {"quarter": "Q1", "hotel_id": "h1", "press_mentions": 1, "toys_distributed": 10, "shelter_hours": 5}
        assert _content_hash(d1) == _content_hash(d2)

    def test_different_hotel_different_sig(self, assembler):
        m = {"toys_distributed": 10}
        r1 = assembler.assemble_receipt("h1", "2026-Q1", m)
        a2 = SBImpactReportAssembler()
        r2 = a2.assemble_receipt("h2", "2026-Q1", m)
        assert r1.value.signature != r2.value.signature


class TestRenewalDetection:
    def test_no_prior_quarter(self, assembler):
        r = assembler.check_renewal("h1")
        assert r.ok and not r.value["needs_renewal"]

    def test_after_receipt(self, assembler):
        assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 5})
        r = assembler.check_renewal("h1")
        assert r.ok and r.value["needs_renewal"] and r.value["last_quarter"] == "2026-Q1"

    def test_none_hotel_id(self, assembler):
        r = assembler.check_renewal(None)
        assert not r.ok

    def test_unknown_hotel(self, assembler):
        r = assembler.check_renewal("unknown")
        assert r.ok and not r.value["needs_renewal"]


class TestGetReceipt:
    def test_existing(self, assembler):
        assembler.assemble_receipt("h1", "2026-Q1", {"toys_distributed": 10})
        r = assembler.get_receipt("h1", "2026-Q1")
        assert r.ok and r.value.toys_distributed == 10

    def test_missing(self, assembler):
        r = assembler.get_receipt("h1", "2026-Q1")
        assert not r.ok


class TestCanonicalJson:
    def test_sorted_keys(self):
        j = _canonical_json({"b": 2, "a": 1})
        assert j == '{"a":1,"b":2}'
