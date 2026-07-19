"""Tests for runner/flaky_test_healer.py"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ["ORCH_FLAKY_TEST_HEALER_ENABLED"] = "true"
os.environ["ORCH_DB_URL"] = ""
os.environ["ORCH_SUPABASE_URL"] = ""
os.environ["ORCH_SUPABASE_KEY"] = ""

import flaky_test_healer


def test_record_test_result_tracks_pass_fail():
    """record_test_result should track pass/fail counts."""
    name = "test_unique_record_001"
    flaky_test_healer.record_test_result(name, True)
    flaky_test_healer.record_test_result(name, True)
    flaky_test_healer.record_test_result(name, False, "AssertionError: 1 != 2")
    # Verify via flake_rate (needs both pass and fail to be non-zero)
    rate = flaky_test_healer.flake_rate(name)
    assert isinstance(rate, float)
    # 1 fail / 3 total = 0.333...
    assert abs(rate - 1.0/3) < 0.01, f"Expected ~0.333, got {rate}"


def test_flake_rate_computes_correctly():
    """flake_rate should return 0 for unknown, >0 for mixed results."""
    assert flaky_test_healer.flake_rate("nonexistent_test_xyz") == 0.0

    name = "test_flake_rate_calc"
    # 2 pass, 2 fail = 50% flake rate
    flaky_test_healer.record_test_result(name, True)
    flaky_test_healer.record_test_result(name, True)
    flaky_test_healer.record_test_result(name, False)
    flaky_test_healer.record_test_result(name, False)
    rate = flaky_test_healer.flake_rate(name)
    assert abs(rate - 0.5) < 0.01, f"Expected 0.5, got {rate}"


def test_quarantine_and_is_quarantined_roundtrip():
    """quarantine + is_quarantined should roundtrip correctly."""
    name = "test_quarantine_roundtrip_check"
    assert flaky_test_healer.is_quarantined(name) is False
    flaky_test_healer.quarantine(name, reason="flaky in CI")
    assert flaky_test_healer.is_quarantined(name) is True


def test_should_block_merge_filters_quarantined():
    """should_block_merge should not block on quarantined-only failures."""
    qname = "test_known_flaky::test_intermittent"
    flaky_test_healer.quarantine(qname, reason="known flaky")

    # Output with only the quarantined test failing
    output_flaky_only = f"FAILED {qname}\n1 failed"
    assert flaky_test_healer.should_block_merge(output_flaky_only) is False

    # Output with a real (non-quarantined) failure
    output_real = f"FAILED {qname}\nFAILED test_real::test_genuine_bug\n2 failed"
    assert flaky_test_healer.should_block_merge(output_real) is True


def test_extract_test_names_parses_output():
    """extract_test_names should pull test names from FAIL/FAILED/ERROR lines."""
    output = (
        "PASS test_foo.py::test_ok\n"
        "FAILED test_bar.py::test_broken\n"
        "ERROR test_baz.py::test_crash\n"
        "FAIL test_qux.py::test_timeout\n"
        "ok 5 tests passed\n"
    )
    names = flaky_test_healer.extract_test_names(output)
    assert isinstance(names, list)
    assert "test_bar.py::test_broken" in names
    assert "test_baz.py::test_crash" in names
    assert "test_qux.py::test_timeout" in names
    assert len(names) == 3, f"Expected 3 failed tests, got {len(names)}: {names}"
