"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836)."""
from runner.evidence_gate_check import check_merge_evidence, dod_log_is_passing

GOOD_LOG = {"test_passed": True, "vacuity_passed": True, "scope_passed": True}
resolves = lambda sha: sha == "abc1234"
never = lambda sha: False


def test_accepts_real_sha_with_passing_dod_log():
    v = check_merge_evidence("abc1234", GOOD_LOG, sha_resolves=resolves)
    assert v.accepted is True and v.reasons == []


def test_rejects_phantom_sha_that_does_not_resolve():
    v = check_merge_evidence("deadbee", GOOD_LOG, sha_resolves=never)
    assert v.accepted is False
    assert any("does not resolve" in r for r in v.reasons)


def test_rejects_missing_or_malformed_sha():
    assert check_merge_evidence("", GOOD_LOG, sha_resolves=resolves).accepted is False
    assert check_merge_evidence("nothex!!", GOOD_LOG, sha_resolves=resolves).accepted is False


def test_rejects_when_dod_log_incomplete():
    assert dod_log_is_passing({"test_passed": True, "vacuity_passed": True}) is False
    v = check_merge_evidence("abc1234", {"test_passed": True, "vacuity_passed": False, "scope_passed": True}, sha_resolves=resolves)
    assert v.accepted is False
    assert any("DoD log" in r for r in v.reasons)


def test_rejects_when_no_dod_log_at_all():
    v = check_merge_evidence("abc1234", None, sha_resolves=resolves)
    assert v.accepted is False
