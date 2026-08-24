"""Truncation-proof differential QA: sorted signature cap + test identifiers.

Two independent bugs are covered here, because fixing only the reported one
(the 6000-char tail) would have left the same defect at smaller scale:

  1. signatures() capped at 200 in ENCOUNTER order, so which failures stayed
     comparable depended on runner ordering.
  2. compare() had nothing but fuzzy line matching, so it could only ever see
     whatever the truncated tail happened to contain.
"""
import differential_qa
import merge_train


def test_signature_cap_is_order_independent():
    lines = [f"b.ts:{i}:1 error TS2322: Type string is not assignable to number {i}"
             for i in range(300)]
    forward = differential_qa.signatures("\n".join(lines))
    backward = differential_qa.signatures("\n".join(reversed(lines)))
    assert forward == backward, "capping must not depend on encounter order"
    assert len(forward) == 200


def test_identifiers_parse_tap_vitest_and_pytest():
    log = "\n".join([
        "not ok 4 - the ledger records every evidence item",
        "× clause gate rejects an unsigned packet 12ms",
        "FAILED tests/test_ledger.py::test_zero_unknown",
        "ok 5 - unrelated passing test",
    ])
    assert differential_qa.test_identifiers(log) == sorted([
        "tests/test_ledger.py::test_zero_unknown",
        "clause gate rejects an unsigned packet",
        "the ledger records every evidence item",
    ])


def test_identifiers_are_deduplicated_and_sorted():
    log = "× beta\n× alpha\n× beta\n"
    assert differential_qa.test_identifiers(log) == ["alpha", "beta"]


def test_identifiers_empty_for_typecheck_output():
    assert differential_qa.test_identifiers(
        "a.ts(1,2): error TS2322: Type string is not assignable to number") == []


def test_compare_prefers_identifiers_over_the_tail():
    # The candidate fails exactly the tests the baseline already fails, but the
    # noise pushes the shared evidence out of any tail-shaped window.
    noise = "\n".join(f"  console.log padding line {i}" for i in range(400))
    baseline = f"× already broken on prod\n{noise}"
    candidate = f"× already broken on prod\n{noise}"
    result = differential_qa.compare(candidate, baseline)
    assert result["basis"] == "test_identifiers"
    assert result["allowed"] is True


def test_compare_blocks_a_new_failing_test_by_identifier():
    baseline = "× already broken on prod"
    candidate = "× already broken on prod\n× newly broken by this candidate"
    result = differential_qa.compare(candidate, baseline)
    assert result["allowed"] is False
    assert result["new"] == ["newly broken by this candidate"]


def test_compare_still_falls_back_to_signatures_without_test_ids():
    base = "a.ts(1,2): error TS2322: Type string is not assignable to number"
    candidate = "a.ts(9,2): error TS2322: Type string is not assignable to number"
    result = differential_qa.compare(candidate, base)
    assert result.get("basis") != "test_identifiers"
    assert result["allowed"] is True


def test_failure_detail_prepends_every_failing_test_and_keeps_the_tail():
    # 900 failures: the tail cannot hold them all, which is the original bug.
    stdout = "\n".join(f"not ok {i} - failing case {i:04d}" for i in range(900))
    detail = merge_train._failure_detail(stdout, "")
    assert merge_train._FAILING_TESTS_HEADER in detail
    assert "failing case 0000" in detail, "an early failure must survive truncation"
    assert "failing case 0899" in detail
    # The raw tail is ADDED to, never substituted.
    assert detail.endswith(stdout[-6000:].strip())


def test_failure_detail_degrades_to_the_tail_without_test_ids():
    stdout = "a.ts(1,2): error TS2322: Type string is not assignable to number"
    assert merge_train._failure_detail(stdout, "") == stdout.strip()
