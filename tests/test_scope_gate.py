"""PROPRIETARY -- Apparently Inc. Trade Secret. Protected under DTSA (18 U.S.C. 1836)."""
from runner.scope_gate import (
    assess_scope,
    files_out_of_scope,
    references_changed_symbol,
    named_test_executed,
)

GREEN = {"collected": 3, "passed": 3, "failed": 0, "errors": 0}


def test_files_out_of_scope():
    assert files_out_of_scope(["server/a.ts", "server/b.ts"], ["server/"]) == []
    assert files_out_of_scope(["server/a.ts", "app/x.vue"], ["server/"]) == ["app/x.vue"]
    # empty declared scope => not enforced
    assert files_out_of_scope(["anything"], []) == []


def test_references_changed_symbol():
    assert references_changed_symbol("expect(verifyPendingFacts(...))", "verifyPendingFacts") is True
    assert references_changed_symbol("expect(somethingElse())", "verifyPendingFacts") is False
    assert references_changed_symbol("", "") is True  # no symbol declared => not enforced


def test_named_test_executed_defends_zero_collected():
    assert named_test_executed(GREEN) is True
    assert named_test_executed({"collected": 0, "passed": 0, "failed": 0}) is False  # spoofed green
    assert named_test_executed({"collected": 2, "passed": 1, "failed": 1}) is False


def test_assess_scope_passes_clean_change():
    r = assess_scope(
        changed_files=["runner/vacuity_gate.py"],
        declared_scope=["runner/"],
        proof_test_source="assess_vacuity(...)",
        changed_symbol="assess_vacuity",
        proof_report=GREEN,
    )
    assert r.passed is True and r.reasons == []


def test_assess_scope_flags_all_violations():
    r = assess_scope(
        changed_files=["runner/x.py", "app/leak.vue"],
        declared_scope=["runner/"],
        proof_test_source="totally unrelated assertions",
        changed_symbol="myFunc",
        proof_report={"collected": 0, "passed": 0, "failed": 0},
    )
    assert r.passed is False
    assert r.out_of_scope == ["app/leak.vue"]
    assert len(r.reasons) == 3  # scope drift + missing symbol + spoofed green
